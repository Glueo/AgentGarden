#!/usr/bin/env python3
"""Materialize secret runtime config and safely patch Hermes configuration."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import yaml

HOME = Path.home()
PROJECT = Path(__file__).resolve().parents[1]
HERMES_CONFIG = HOME / ".hermes/config.yaml"

# ── AnyRouter routing ─────────────────────────────────────────────────
# AnyRouter serves GPT only. Its Claude models were dropped in 2026-09
# after they proved unusable in practice, which also retired the
# ``anthropic_messages`` twin entry and the source patch that taught Hermes
# to send AnyRouter's ``context-1m-2025-08-07`` opt-in. Claude now reaches
# the Garden only through providers that serve it natively.
ANYROUTER_BASE_URL = "https://anyrouter.top/v1"
ANYROUTER_GPT = "anyrouter"
ANYROUTER_RETIRED = "anyrouter-claude"
ANYROUTER_CONTEXT_LENGTH = 1_000_000
ANYROUTER_PRIMARY_MODEL = "gpt-6-astra"
ANYROUTER_SOL_MODEL = "gpt-5.6-sol"
ANYROUTER_GPT_MODELS = (ANYROUTER_PRIMARY_MODEL, ANYROUTER_SOL_MODEL)

# Use the standard OpenAI Codex route. The prior Hermes-only ``-900k``
# selector variant has been retired along with the profile that defined it.
# Keeping the bare model id here makes a future runtime install converge on
# the supported 272K Codex context instead of resurrecting that local alias.
OPENAI_PROVIDER = "openai-codex"
OPENAI_MODEL = "gpt-5.6-sol"

# The interactive coordinator and its unpinned delegate_task children share
# one route: AnyRouter Astra first, then AnyRouter SOL, the OpenAI subscription,
# and finally the limited paid Micu SOL route.
MAIN_FALLBACKS = [
    {
        "provider": ANYROUTER_GPT,
        "model": ANYROUTER_SOL_MODEL,
        "api_mode": "codex_responses",
    },
    {"provider": OPENAI_PROVIDER, "model": OPENAI_MODEL},
    {"provider": "micu-api", "model": "gpt-5.6-sol"},
]
AUXILIARY_FALLBACKS = [
    {"provider": OPENAI_PROVIDER, "model": OPENAI_MODEL},
]

AUXILIARY_TASKS = (
    "title_generation", "approval", "compression", "memory_query_rewrite", "goal_judge",
)

HERMES_ENV = HOME / ".hermes/.env"
HERMES_SKILLS = HOME / ".hermes/skills"
HERMES_PROFILES = HOME / ".hermes/profiles"
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


def patch_skill_config(config: dict, *, shared_root: bool) -> dict:
    """Use Hermes' native skill root and disable autonomous maintenance."""
    skills = {**(config.get("skills") or {})}
    raw_external = skills.get("external_dirs") or []
    if isinstance(raw_external, str):
        raw_external = [raw_external]
    garden_skills = str(PROJECT / "garden/skills")

    def is_profile_skill_dir(value: str) -> bool:
        try:
            relative = Path(value).expanduser().relative_to(HERMES_PROFILES)
        except ValueError:
            return False
        return len(relative.parts) == 2 and relative.parts[1] == "skills"

    external = []
    for item in raw_external:
        value = str(item)
        if value == garden_skills or is_profile_skill_dir(value):
            continue
        external.append(value)
    if shared_root:
        external.append(str(HERMES_SKILLS))
    skills.update({
        "external_dirs": list(dict.fromkeys(external)),
        "creation_nudge_interval": 0,
        "write_approval": True,
        "ledger": True,
    })
    config["skills"] = skills
    config["curator"] = {
        **(config.get("curator") or {}),
        "enabled": False,
    }
    auxiliary = {**(config.get("auxiliary") or {})}
    auxiliary["background_review"] = {
        **(auxiliary.get("background_review") or {}),
        "enabled": False,
    }
    config["auxiliary"] = auxiliary
    return config


def remove_micu_non_main_routes(config: dict) -> dict:
    """Reserve every Micu route for the default profile's final fallback."""
    direct_routes = [
        ("model", config.get("model")),
        ("delegation", config.get("delegation")),
        *[
            (f"auxiliary.{name}", route)
            for name, route in (config.get("auxiliary") or {}).items()
        ],
    ]
    for name, route in direct_routes:
        if isinstance(route, dict) and route.get("provider") == "micu-api":
            raise RuntimeError(f"Micu direct route is forbidden outside the default profile: {name}")

    def without_micu(entries: list[dict] | None) -> list[dict]:
        return [entry for entry in (entries or []) if entry.get("provider") != "micu-api"]

    config["fallback_providers"] = without_micu(config.get("fallback_providers"))
    for task in (config.get("auxiliary") or {}).values():
        if not isinstance(task, dict) or "fallback_chain" not in task:
            continue
        task["fallback_chain"] = without_micu(task.get("fallback_chain"))
    delegation = config.get("delegation") or {}
    if isinstance(delegation, dict) and "fallback_providers" in delegation:
        delegation["fallback_providers"] = without_micu(delegation.get("fallback_providers"))
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


def normalize_anyrouter_provider(config: dict, *, selected_model: str) -> dict:
    """Keep exactly one AnyRouter entry, on the GPT surface.

    Also drops the retired ``anyrouter-claude`` twin and the
    ``context_1m_beta`` opt-in it needed. Both are removed on every run
    rather than merely not created, so a config still carrying them from an
    earlier install converges instead of keeping a provider whose requests
    only ever fail.
    """
    providers = config.get("custom_providers") or []
    gpt_entry = None
    rest = []
    for item in providers:
        name = item.get("name")
        if name == ANYROUTER_GPT:
            gpt_entry = item
        elif name != ANYROUTER_RETIRED:
            rest.append(item)
    if gpt_entry is None:
        raise RuntimeError("Hermes provider not found: anyrouter")

    models = {
        alias: value
        for alias, value in (gpt_entry.get("models") or {}).items()
        if not str(alias).startswith("claude-")
    }
    gpt_entry.pop("context_1m_beta", None)
    gpt_entry.update({
        "name": ANYROUTER_GPT,
        "base_url": ANYROUTER_BASE_URL,
        "api_mode": "codex_responses",
        # AnyRouter requires this marker even when stale reasoning replay is disabled.
        "extra_body": {
            **(gpt_entry.get("extra_body") or {}),
            "include": ["reasoning.encrypted_content"],
        },
        "models": normalized_anyrouter_models(models, ANYROUTER_GPT_MODELS),
        "model": selected_model,
    })
    config["custom_providers"] = [*rest, gpt_entry]
    return config


def patch_hermes_config(config: dict) -> dict:
    """Apply the reproducible, non-secret Agent Garden Hermes settings."""
    config["custom_providers"] = [
        item for item in config.get("custom_providers", [])
        if item.get("name") != "huoshan"
    ]

    normalize_anyrouter_provider(config, selected_model=ANYROUTER_PRIMARY_MODEL)

    config["model"] = {
        **(config.get("model") or {}),
        "default": ANYROUTER_PRIMARY_MODEL,
        "provider": ANYROUTER_GPT,
        "api_mode": "codex_responses",
    }
    config["fallback_providers"] = [dict(entry) for entry in MAIN_FALLBACKS]
    delegation = {**(config.get("delegation") or {})}
    # An unpinned child inherits both the parent's active primary route and its
    # fallback chain. Remove stale routing overrides instead of copying the
    # chain so future main-route changes apply to delegate_task automatically.
    for key in ("provider", "model", "base_url", "api_key", "api_mode", "fallback_providers"):
        delegation.pop(key, None)
    config["delegation"] = delegation


    config["terminal"] = {
        **(config.get("terminal") or {}),
        "cwd": str(PROJECT),
    }
    patch_skill_config(config, shared_root=False)
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
        # Give every provider hop five API attempts before fallback.
        "api_max_retries": 5,
    }
    config["sessions"] = {
        **(config.get("sessions") or {}),
        # Soft-hide inactive history; never delete sessions automatically.
        "auto_archive": True,
        "auto_archive_days": 7,
        "auto_prune": False,
    }
    auxiliary = {
        **(config.get("auxiliary") or {}),
        # Do not repeat the same failed auxiliary request before fallback.
        "transient_retries": 0,
    }
    for task in AUXILIARY_TASKS:
        auxiliary[task] = {
            **(auxiliary.get(task) or {}),
            "provider": ANYROUTER_GPT,
            "model": ANYROUTER_SOL_MODEL,
            # Micu SOL is reserved for the coordinator and its unpinned
            # delegate_task children. Auxiliary work starts on AnyRouter and
            # may use the OpenAI subscription, but never consumes Micu.
            "fallback_chain": [dict(entry) for entry in AUXILIARY_FALLBACKS],
        }
    auxiliary["background_review"] = {
        **(auxiliary.get("background_review") or {}),
        "enabled": False,
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


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def patch_openviking_config(existing: dict, *, vlm_key: str, embedding_key: str) -> dict:
    """Pin OpenViking to the single approved Doubao VLM route."""
    config = existing
    config.setdefault("default_account", "default")
    config.setdefault("default_user", "gwen")
    server = config.setdefault("server", {})
    server.update({"host": "127.0.0.1", "port": 1933, "auth_mode": "dev", "cors_origins": ["http://127.0.0.1:1933"]})
    storage = config.setdefault("storage", {})
    storage.setdefault("workspace", str(OV_DATA))
    storage.setdefault("agfs", {"backend": "local"})
    storage.setdefault("vectordb", {"backend": "local", "dimension": 1024})
    embedding = config.setdefault("embedding", {})
    embedding.setdefault("dense", {
        "provider": "volcengine",
        "api_key": embedding_key,
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-embedding-vision-251215",
        "dimension": 1024,
        "input": "multimodal",
        "batch_size": 8,
    })
    config["vlm"] = {
        "provider": "volcengine",
        "api_key": vlm_key,
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-2-0-lite-260215",
        "temperature": 0.0,
        "max_retries": 1,
        "max_concurrent": 4,
        "timeout": 180.0,
    }
    memory = config.setdefault("memory", {})
    memory["custom_templates_dir"] = str(PROJECT / "openviking/memory-templates")
    config.setdefault("rerank", {})
    config.setdefault("output_language_override", "")
    return config


def approved_vlm_key(existing: dict) -> str | None:
    vlm = existing.get("vlm") or {}
    api_base = str(vlm.get("api_base") or "")
    if vlm.get("provider") != "volcengine" or api_base != "https://ark.cn-beijing.volces.com/api/v3":
        return None
    value = vlm.get("api_key")
    return value if isinstance(value, str) and value else None


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


def main() -> int:
    config = yaml.safe_load(HERMES_CONFIG.read_text(encoding="utf-8"))
    existing_ov = json.loads(OV_CONFIG.read_text(encoding="utf-8")) if OV_CONFIG.exists() else {}
    vlm_key = approved_vlm_key(existing_ov)
    try:
        huoshan_key = provider(config, "huoshan").get("api_key")
    except RuntimeError:
        huoshan_key = existing_ov.get("embedding", {}).get("dense", {}).get("api_key")
    if not vlm_key or not huoshan_key:
        raise RuntimeError("Required OpenViking VLM or embedding API key is missing")

    ov = patch_openviking_config(existing_ov, vlm_key=vlm_key, embedding_key=huoshan_key)
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
    for profile_config in sorted(HERMES_PROFILES.glob("*/config.yaml")):
        backup(profile_config)
        profile = yaml.safe_load(profile_config.read_text(encoding="utf-8")) or {}
        remove_micu_non_main_routes(profile)
        patch_skill_config(profile, shared_root=True)
        write_private(
            profile_config,
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        )
    patch_env(HERMES_ENV, {"OPENVIKING_ENDPOINT": "http://127.0.0.1:1933", "OPENVIKING_ACCOUNT": "default", "OPENVIKING_USER": "gwen", "OPENVIKING_AGENT": "hermes"})
    remove_env_keys(HERMES_ENV, {"TERMINAL_CWD", "MESSAGING_CWD"})
    print("Runtime configuration installed; secrets remained outside the project.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
