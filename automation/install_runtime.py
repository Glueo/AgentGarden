#!/usr/bin/env python3
"""Materialize secret runtime config and safely patch Hermes configuration."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml

HOME = Path.home()
PROJECT = Path(__file__).resolve().parents[1]
HERMES_CONFIG = HOME / ".hermes/config.yaml"

# ── Retired AnyRouter route cleanup ──────────────────────────────────
# AnyRouter serves GPT only. Its Claude models were dropped in 2026-09
# after they proved unusable in practice, which also retired the
# ``anthropic_messages`` twin entry and the source patch that taught Hermes
# to send AnyRouter's ``context-1m-2025-08-07`` opt-in. Claude now reaches
# the Garden only through providers that serve it natively.
ANYROUTER_BASE_URL = "https://anyrouter.top/v1"
ANYROUTER_GPT = "anyrouter"
ANYROUTER_KEY_ENV = "ANYROUTER_API_KEY"
ANYROUTER_RETIRED = "anyrouter-claude"


CODERAPI_BASE_URL = "https://wcf.coderapi.vip/v1"
CODERAPI_KEY_ENV = "CODERAPI_API_KEY"
CODERAPI_MODEL = "codex-auto-review-openai-compact"
CODERAPI_PROVIDER = "coderapi"

AUXILIARY_TASKS = (
    "approval",
    "background_review",
    "compression",
    "curator",
    "goal_judge",
    "kanban_decomposer",
    "mcp",
    "memory_query_rewrite",
    "monitor",
    "moa_aggregator",
    "moa_reference",
    "profile_describer",
    "review",
    "skills_hub",
    "title_generation",
    "triage_specifier",
    "tts_audio_tags",
    "vision",
)

HERMES_ENV = HOME / ".hermes/.env"
OV_DIR = HOME / ".openviking"
OV_CONFIG = OV_DIR / "ov.conf"
OVCLI_CONFIG = OV_DIR / "ovcli.conf"
OV_DATA = HOME / "Library/Application Support/agent-garden/openviking"


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.agent-garden.bak"))


def provider(config: dict, name: str) -> dict:
    for item in config.get("custom_providers", []):
        if item.get("name") == name:
            return item
    raise RuntimeError(f"Hermes provider not found: {name}")


def remove_fallback_settings(value) -> None:
    """Remove every explicitly configured fallback route in place."""
    if isinstance(value, dict):
        for key in list(value):
            if "fallback" in str(key).lower():
                value.pop(key)
            else:
                remove_fallback_settings(value[key])
    elif isinstance(value, list):
        for item in value:
            remove_fallback_settings(item)


def patch_skill_config(config: dict) -> dict:
    """Use Hermes' native skill root and native self-improvement defaults."""
    skills = {**(config.get("skills") or {})}
    skills.pop("creation_nudge_interval", None)
    skills.update({
        "external_dirs": [],
        "write_approval": True,
        "ledger": True,
    })
    config["skills"] = skills
    curator = {**(config.get("curator") or {})}
    curator.pop("enabled", None)
    if curator:
        curator["consolidate"] = False
        config["curator"] = curator
    else:
        config.pop("curator", None)
    auxiliary = {**(config.get("auxiliary") or {})}
    background_review = {**(auxiliary.get("background_review") or {})}
    background_review.pop("enabled", None)
    if background_review:
        auxiliary["background_review"] = background_review
    else:
        auxiliary.pop("background_review", None)
    config["auxiliary"] = auxiliary
    return config


def normalize_anyrouter_provider(config: dict) -> dict:
    """Remove retired AnyRouter routes without selecting the main model.

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
        config["custom_providers"] = rest
        return config

    gpt_entry.pop("api_key", None)
    gpt_entry.pop("context_1m_beta", None)
    models = {
        alias: details
        for alias, details in (gpt_entry.get("models") or {}).items()
        if alias != "gpt-5.6-sol" and not alias.lower().startswith("claude")
    }
    selected_model = str(gpt_entry.get("model") or "")
    if selected_model == "gpt-5.6-sol" or selected_model.lower().startswith("claude"):
        gpt_entry.pop("model", None)
    gpt_entry.update({
        "name": ANYROUTER_GPT,
        "base_url": ANYROUTER_BASE_URL,
        "api_mode": "codex_responses",
        "key_env": ANYROUTER_KEY_ENV,
        # AnyRouter requires this marker even when stale reasoning replay is disabled.
        "extra_body": {
            **(gpt_entry.get("extra_body") or {}),
            "include": ["reasoning.encrypted_content"],
        },
        "models": models,
    })
    config["custom_providers"] = [*rest, gpt_entry]
    return config


def patch_hermes_config(config: dict) -> dict:
    """Apply the reproducible, non-secret Agent Garden Hermes settings."""
    remove_fallback_settings(config)
    config["custom_providers"] = [
        {**original} for original in config.get("custom_providers", [])
    ]

    named_providers = {**(config.get("providers") or {})}
    coderapi = {**(named_providers.get(CODERAPI_PROVIDER) or {})}
    for key in ("api_key", "base_url", "url", "api_mode", "model"):
        coderapi.pop(key, None)
    coderapi.update({
        "api": CODERAPI_BASE_URL,
        "key_env": CODERAPI_KEY_ENV,
        "transport": "chat_completions",
        "default_model": CODERAPI_MODEL,
        "models": {CODERAPI_MODEL: {"name": CODERAPI_MODEL}},
    })
    named_providers[CODERAPI_PROVIDER] = coderapi
    config["providers"] = named_providers

    normalize_anyrouter_provider(config)
    delegation = {**(config.get("delegation") or {})}
    # An unpinned child inherits the active primary route. Remove stale routing
    # overrides so future main-route changes apply automatically.
    for key in ("provider", "model", "base_url", "api_key", "api_mode", "fallback_providers"):
        delegation.pop(key, None)
    config["delegation"] = delegation


    config["terminal"] = {
        **(config.get("terminal") or {}),
        "cwd": str(PROJECT),
    }
    patch_skill_config(config)
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
        # Retry transient failures on the selected main provider before surfacing them.
        "api_max_retries": 5,
    }
    config["sessions"] = {
        **(config.get("sessions") or {}),
        # Soft-hide inactive history; never delete sessions automatically.
        "auto_archive": True,
        "auto_archive_days": 7,
        "auto_prune": False,
    }
    auxiliary = {**(config.get("auxiliary") or {})}
    auxiliary.pop("transient_retries", None)
    stream_only = auxiliary.get("stream_only_base_urls")
    stream_only = list(stream_only) if isinstance(stream_only, list) else []
    if "wcf.coderapi.vip" not in stream_only:
        stream_only.append("wcf.coderapi.vip")
    auxiliary["stream_only_base_urls"] = stream_only
    task_names = set(AUXILIARY_TASKS)
    task_names.update(
        name for name, value in auxiliary.items() if isinstance(value, dict)
    )
    for task in sorted(task_names):
        route = {**(auxiliary.get(task) or {})}
        for key in ("base_url", "api_key", "api_mode"):
            route.pop(key, None)
        route.update({"provider": CODERAPI_PROVIDER, "model": CODERAPI_MODEL})
        auxiliary[task] = route
    config["auxiliary"] = auxiliary
    remove_fallback_settings(config)
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
    memory.pop("custom_templates_dir", None)
    if not memory:
        config.pop("memory")
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


def env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            return value or None
    return None


def required_coderapi_key(config: dict, env_path: Path) -> str:
    named = config.get("providers") or {}
    coderapi = named.get(CODERAPI_PROVIDER) if isinstance(named, dict) else None
    inline = coderapi.get("api_key") if isinstance(coderapi, dict) else None
    value = os.environ.get(CODERAPI_KEY_ENV) or env_value(env_path, CODERAPI_KEY_ENV) or inline
    if not value:
        raise RuntimeError(f"Required {CODERAPI_KEY_ENV} is missing")
    return value


def main() -> int:
    config = yaml.safe_load(HERMES_CONFIG.read_text(encoding="utf-8"))
    coderapi_key = required_coderapi_key(config, HERMES_ENV)
    try:
        anyrouter_key = provider(config, ANYROUTER_GPT).get("api_key")
    except RuntimeError:
        anyrouter_key = None
    model_config = config.get("model") or {}
    if model_config.get("provider") == ANYROUTER_GPT:
        anyrouter_key = anyrouter_key or model_config.get("api_key")
        if anyrouter_key:
            model_config.pop("api_key", None)
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
    env_values = {
        "OPENVIKING_ENDPOINT": "http://127.0.0.1:1933",
        "OPENVIKING_ACCOUNT": "default",
        "OPENVIKING_USER": "gwen",
        "OPENVIKING_AGENT": "hermes",
        CODERAPI_KEY_ENV: coderapi_key,
    }
    if anyrouter_key:
        env_values[ANYROUTER_KEY_ENV] = anyrouter_key
    patch_env(HERMES_ENV, env_values)
    remove_env_keys(HERMES_ENV, {"TERMINAL_CWD", "MESSAGING_CWD"})
    print("Runtime configuration installed; secrets remained outside the project.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
