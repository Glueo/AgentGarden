#!/usr/bin/env python3
"""Materialize secret runtime config and safely patch Hermes configuration."""

from __future__ import annotations

import json
import os
import shutil
import importlib.util
from datetime import datetime
from pathlib import Path

import yaml

HOME = Path.home()
PROJECT = Path(__file__).resolve().parents[1]
HERMES_CONFIG = HOME / ".hermes/config.yaml"

# ── AnyRouter routing ─────────────────────────────────────────────────
# AnyRouter fronts both GPT and Claude, but Hermes resolves ``api_mode``
# per provider entry, not per model (hermes_cli/runtime_provider.py), and
# the two families need different wire formats: GPT answers on
# /v1/responses (codex_responses) while Claude answers only on
# /v1/messages (chat_completions 404s there). So the one upstream is
# declared twice, same base URL and key, once per API surface.
ANYROUTER_BASE_URL = "https://anyrouter.top/v1"
ANYROUTER_GPT = "anyrouter"
ANYROUTER_CLAUDE = "anyrouter-claude"
# AnyRouter rejects every Claude request that does not opt into the 1M
# window. Model entries must declare it, and the provider must carry the
# ``context_1m_beta`` flag that patch_hermes_source.py teaches Hermes to
# read (the beta header is otherwise Azure-only and unreachable from
# config). Applied to the GPT entry too — the same account gate covers it.
ANYROUTER_CONTEXT_LENGTH = 1_000_000
ANYROUTER_GPT_MODELS = ("gpt-5.6-sol",)
ANYROUTER_CLAUDE_MODELS = ("claude-fable-5-1", "claude-opus-5", "claude-opus-4-8")

# ``-900k`` is a Hermes-side picker suffix, not a distinct upstream model:
# it is stripped before the id hits the wire, and only opts the slug into
# the large window. Codex subscriptions advertise a stale 272K while the
# real ceiling was measured at ~911K input tokens (1.05M minus output
# headroom); Hermes exposes 900K to keep margin. See
# agent/model_metadata.py::_CODEX_OAUTH_VERIFIED_ABOVE_ADVERTISED_PREFIXES.
# So this IS the single unified OpenAI model — the bare slug would silently
# cap the same model at 272K.
OPENAI_PROVIDER = "openai-codex"
OPENAI_MODEL = "gpt-5.6-sol-900k"

# One chain, used for the interactive coordinator and mirrored onto every
# auxiliary task: AnyRouter SOL, then AnyRouter Claude, then the OpenAI
# subscription, and only then the paid micu relay.
#
# ``api_mode`` is spelled out on every AnyRouter hop. A fallback entry
# defaults to chat_completions and only auto-detects anthropic_messages for
# hosts Hermes recognizes as Anthropic (chat_completion_helpers.py:2791) --
# anyrouter.top is not one, so an unpinned Claude hop is sent over the
# OpenAI wire and comes back 404 "当前 API 不支持所选模型". An explicit
# api_mode on the entry always wins, which is what makes the split routable
# from the chain and not just from the provider entry.
MAIN_FALLBACKS = [
    {
        "provider": ANYROUTER_CLAUDE,
        "model": "claude-opus-5",
        "api_mode": "anthropic_messages",
    },
    {"provider": OPENAI_PROVIDER, "model": OPENAI_MODEL},
    {"provider": "micu-api", "model": "gpt-5.6-terra"},
]

AUXILIARY_TASKS = ("title_generation", "approval", "compression", "memory_query_rewrite")

HERMES_ENV = HOME / ".hermes/.env"
DREAMER_PROFILE_CONFIG = HOME / ".hermes/profiles/dreamer/config.yaml"
DREAMER_SKILLS = HOME / ".hermes/profiles/dreamer/skills"
OV_DIR = HOME / ".openviking"
OV_CONFIG = OV_DIR / "ov.conf"
OVCLI_CONFIG = OV_DIR / "ovcli.conf"
OV_DATA = HOME / "Library/Application Support/agent-garden/openviking"


def backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.agent-garden-{stamp}.bak"))


def provider(config: dict, name: str) -> dict:
    for item in config.get("custom_providers", []):
        if item.get("name") == name:
            return item
    raise RuntimeError(f"Hermes provider not found: {name}")


def first_provider(config: dict, *names: str) -> dict:
    for name in names:
        try:
            return provider(config, name)
        except RuntimeError:
            continue
    raise RuntimeError(f"Hermes provider not found: {', '.join(names)}")


def patch_skill_ownership(config: dict, *, dreamer_owner: bool) -> dict:
    """Keep Dreamer as the only mutable source for distilled skills."""
    skills = {**(config.get("skills") or {})}
    raw_external = skills.get("external_dirs") or []
    if isinstance(raw_external, str):
        raw_external = [raw_external]
    garden_skills = str(PROJECT / "garden/skills")
    dreamer_skills = str(DREAMER_SKILLS)
    external = [
        str(item) for item in raw_external
        if str(item) not in {garden_skills, dreamer_skills}
    ]
    if not dreamer_owner:
        external.append(dreamer_skills)
    skills.update({
        "external_dirs": list(dict.fromkeys(external)),
        # Per-chat nudges stay off. The scheduled Dream is the sole writer.
        "creation_nudge_interval": 0,
        # Dreamer can maintain its local skills unattended; consumers cannot
        # mutate those external skills through autonomous curation.
        "write_approval": not dreamer_owner,
    })
    config["skills"] = skills
    return config


def normalized_anyrouter_models(existing: dict, wanted: tuple[str, ...]) -> dict:
    """Rebuild an AnyRouter models mapping, repairing corrupted entries.

    An earlier run splayed model-name strings into ``{'0': 'c', '1': 'l', ...}``
    character maps and left ``name`` holding a display label ("Claude Opus 5")
    or an empty string instead of the wire id. Neither is valid model
    metadata, so digit keys are dropped and ``name`` is reset to the alias --
    safe here because every AnyRouter alias IS its wire id, unlike the camel
    and micu entries where alias and name legitimately differ.
    """
    clean: dict = {}
    for alias, config in (existing or {}).items():
        if not isinstance(config, dict):
            continue
        clean[alias] = {
            key: value for key, value in config.items() if not str(key).isdigit()
        }
    for alias in wanted:
        clean.setdefault(alias, {})
    return {
        alias: {**config, "name": alias, "context_length": ANYROUTER_CONTEXT_LENGTH}
        for alias, config in clean.items()
    }


def split_anyrouter_providers(config: dict) -> dict:
    """Declare the AnyRouter upstream once per API surface, GPT and Claude.

    Claude models are moved out of the codex_responses entry: left there they
    are unreachable (that surface 404s them) and they would shadow the
    anthropic_messages entry when a fallback names them.
    """
    providers = config.get("custom_providers") or []
    gpt_entry = None
    claude_entry = None
    rest = []
    for item in providers:
        name = item.get("name")
        if name == ANYROUTER_GPT:
            gpt_entry = item
        elif name == ANYROUTER_CLAUDE:
            claude_entry = item
        else:
            rest.append(item)
    if gpt_entry is None:
        raise RuntimeError("Hermes provider not found: anyrouter")

    inherited = {**(claude_entry or {})}
    previous_models = {**(gpt_entry.get("models") or {}), **(inherited.get("models") or {})}
    claude_models = {
        alias: value
        for alias, value in previous_models.items()
        if str(alias).startswith("claude-")
    }
    gpt_models = {
        alias: value
        for alias, value in previous_models.items()
        if not str(alias).startswith("claude-")
    }

    gpt_entry.update({
        "name": ANYROUTER_GPT,
        "base_url": ANYROUTER_BASE_URL,
        "api_mode": "codex_responses",
        "models": normalized_anyrouter_models(gpt_models, ANYROUTER_GPT_MODELS),
        "model": "gpt-5.6-sol",
        "context_1m_beta": True,
    })
    claude_entry = {
        **inherited,
        "name": ANYROUTER_CLAUDE,
        "base_url": ANYROUTER_BASE_URL,
        "api_key": gpt_entry.get("api_key"),
        "api_mode": "anthropic_messages",
        "models": normalized_anyrouter_models(claude_models, ANYROUTER_CLAUDE_MODELS),
        "model": "claude-opus-5",
        "context_1m_beta": True,
    }
    config["custom_providers"] = [*rest, gpt_entry, claude_entry]
    return config


def patch_hermes_config(config: dict) -> dict:
    """Apply the reproducible, non-secret Agent Garden Hermes settings."""
    config["custom_providers"] = [
        item for item in config.get("custom_providers", [])
        if item.get("name") != "huoshan"
    ]

    split_anyrouter_providers(config)

    config["model"] = {
        **(config.get("model") or {}),
        "default": "gpt-5.6-sol",
        "provider": ANYROUTER_GPT,
        "api_mode": "codex_responses",
    }
    config["fallback_providers"] = [dict(entry) for entry in MAIN_FALLBACKS]


    config["terminal"] = {
        **(config.get("terminal") or {}),
        "cwd": str(PROJECT),
    }
    patch_skill_ownership(config, dreamer_owner=False)
    config["memory"] = {
        **(config.get("memory") or {}),
        "provider": "openviking",
    }
    config["web"] = {
        **(config.get("web") or {}),
        # Keep keyless DDGS for search and use Tavily only for native extraction.
        "search_backend": "ddgs",
        "extract_backend": "tavily",
    }
    config["agent"] = {
        **(config.get("agent") or {}),
        # Retry each provider up to three times after its initial API attempt.
        "api_max_retries": 3,
    }
    config["sessions"] = {
        **(config.get("sessions") or {}),
        # Soft-hide inactive history; never delete sessions automatically.
        "auto_archive": True,
        "auto_archive_days": 7,
    }
    auxiliary = {
        **(config.get("auxiliary") or {}),
        # Do not repeat the same failed auxiliary request before fallback.
        "transient_retries": 0,
    }
    for task in AUXILIARY_TASKS:
        auxiliary[task] = {
            **(auxiliary.get(task) or {}),
            "provider": "auto",
            # Same order as the main chain, so a provider outage moves the
            # small calls (titles, approvals, compression) exactly where it
            # moves the conversation.
            "fallback_chain": [dict(entry) for entry in MAIN_FALLBACKS],
        }
    config["auxiliary"] = auxiliary


    for item in config.get("custom_providers", []):
        item_models = item.get("models") or {}
        if not isinstance(item_models, dict):
            raise RuntimeError(f"Provider {item.get('name')} models must be a mapping")
        for alias, model_config in item_models.items():
            if not isinstance(model_config, dict) or not model_config.get("name"):
                raise RuntimeError(
                    f"Provider {item.get('name')} model {alias} is malformed"
                )
    return config


def patch_dreamer_profile_config(config: dict) -> dict:
    """Point the dedicated Dream profile at Claude, GPT only as a backstop.

    Distillation is the one job in the Garden that is judged on writing
    quality rather than throughput, so it leads with Fable and falls back
    through Opus before giving up on Claude entirely.
    """
    split_anyrouter_providers(config)
    config["model"] = {
        **(config.get("model") or {}),
        "default": "claude-fable-5-1",
        "provider": ANYROUTER_CLAUDE,
        "api_mode": "anthropic_messages",
    }
    config["fallback_providers"] = [
        {
            "provider": ANYROUTER_CLAUDE,
            "model": "claude-opus-5",
            "api_mode": "anthropic_messages",
        },
        {
            "provider": ANYROUTER_GPT,
            "model": "gpt-5.6-sol",
            "api_mode": "codex_responses",
        },
        {"provider": "micu-api", "model": "gpt-5.6-sol"},
    ]

    config["agent"] = {
        **(config.get("agent") or {}),
        "api_max_retries": 3,
    }
    config["web"] = {
        **(config.get("web") or {}),
        "search_backend": "ddgs",
        "extract_backend": "tavily",
    }
    patch_skill_ownership(config, dreamer_owner=True)
    return config


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def patch_env(path: Path, values: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keys = set(values)
    kept = [line for line in existing if not any(line.startswith(f"{key}=") for key in keys)]
    kept.extend(f"{key}={value}" for key, value in values.items())
    write_private(path, "\n".join(kept) + "\n")


def remove_env_keys(path: Path, keys: set[str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [line for line in existing if not any(line.startswith(f"{key}=") for key in keys)]
    write_private(path, "\n".join(kept) + "\n")


def apply_source_patches() -> list[str]:
    """Re-apply the Hermes source patches, loaded by path.

    Imported lazily rather than at module scope because install_runtime is
    itself loaded by path in the tests, where a sibling import would not
    resolve.
    """
    spec = importlib.util.spec_from_file_location(
        "patch_hermes_source", PROJECT / "automation/patch_hermes_source.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main()


def main() -> int:
    config = yaml.safe_load(HERMES_CONFIG.read_text(encoding="utf-8"))
    camel = first_provider(config, "camel-openviking", "camel")
    try:
        huoshan_key = provider(config, "huoshan").get("api_key")
    except RuntimeError:
        existing_ov = json.loads(OV_CONFIG.read_text(encoding="utf-8")) if OV_CONFIG.exists() else {}
        huoshan_key = existing_ov.get("embedding", {}).get("dense", {}).get("api_key")
    if not camel.get("api_key") or not huoshan_key:
        raise RuntimeError("Required Camel or Volcengine API key is missing")

    ov = {
        "default_account": "default",
        "default_user": "gwen",
        "server": {"host": "127.0.0.1", "port": 1933, "auth_mode": "dev", "cors_origins": ["http://127.0.0.1:1933"]},
        "storage": {"workspace": str(OV_DATA), "agfs": {"backend": "local"}, "vectordb": {"backend": "local", "dimension": 1024}},
        "embedding": {"dense": {"provider": "volcengine", "api_key": huoshan_key, "api_base": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-embedding-vision-251215", "dimension": 1024, "input": "multimodal", "batch_size": 8}},
        "vlm": {"provider": "openai", "api_key": camel["api_key"], "api_base": camel.get("base_url", "https://api.camel-hub.cn/v1"), "model": "doubao-seed-2-0-lite-260215", "temperature": 0.0, "max_retries": 3, "max_concurrent": 4, "timeout": 180.0},
        "rerank": {},
        "output_language_override": "",
    }
    ovcli = {"url": "http://127.0.0.1:1933", "account": "default", "user": "gwen", "timeout": 180}
    OV_DIR.mkdir(parents=True, exist_ok=True)
    OV_DATA.mkdir(parents=True, exist_ok=True)
    backup(OV_CONFIG)
    backup(OVCLI_CONFIG)
    write_private(OV_CONFIG, json.dumps(ov, ensure_ascii=False, indent=2) + "\n")
    write_private(OVCLI_CONFIG, json.dumps(ovcli, ensure_ascii=False, indent=2) + "\n")

    backup(HERMES_CONFIG)
    config = patch_hermes_config(config)
    write_private(HERMES_CONFIG, yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    if DREAMER_PROFILE_CONFIG.exists():
        backup(DREAMER_PROFILE_CONFIG)
        dreamer_config = yaml.safe_load(
            DREAMER_PROFILE_CONFIG.read_text(encoding="utf-8")
        )
        dreamer_config = patch_dreamer_profile_config(dreamer_config)
        write_private(
            DREAMER_PROFILE_CONFIG,
            yaml.safe_dump(dreamer_config, allow_unicode=True, sort_keys=False),
        )
    profiles_root = HOME / ".hermes/profiles"
    for profile_config in sorted(profiles_root.glob("*/config.yaml")):
        if profile_config == DREAMER_PROFILE_CONFIG:
            continue
        backup(profile_config)
        profile = yaml.safe_load(profile_config.read_text(encoding="utf-8")) or {}
        patch_skill_ownership(profile, dreamer_owner=False)
        write_private(
            profile_config,
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        )
    patch_env(HERMES_ENV, {"OPENVIKING_ENDPOINT": "http://127.0.0.1:1933", "OPENVIKING_ACCOUNT": "default", "OPENVIKING_USER": "gwen", "OPENVIKING_AGENT": "hermes"})
    remove_env_keys(HERMES_ENV, {"TERMINAL_CWD", "MESSAGING_CWD"})
    for name in apply_source_patches():
        print(f"Re-applied Hermes source patch: {name}")
    print("Runtime configuration installed; secrets remained outside the project.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
