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
HERMES_ENV = HOME / ".hermes/.env"
DREAMER_PROFILE_CONFIG = HOME / ".hermes/profiles/dreamer/config.yaml"
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


def patch_hermes_config(config: dict) -> dict:
    """Apply the reproducible, non-secret Agent Garden Hermes settings."""
    config["custom_providers"] = [
        item for item in config.get("custom_providers", [])
        if item.get("name") != "huoshan"
    ]

    anyrouter = provider(config, "anyrouter")
    models = anyrouter.get("models")
    if not isinstance(models, dict):
        models = {}
    models.update({
        "claude-opus-5": {
            "name": "claude-opus-5",
            "context_length": 1000000,
        },
        "claude-opus-4-8": {
            "name": "claude-opus-4-8",
            "context_length": 1000000,
        },
    })
    anyrouter["models"] = models

    config["model"] = {
        **(config.get("model") or {}),
        "default": "gpt-5.6-sol",
        "provider": "anyrouter",
        "api_mode": "codex_responses",
    }
    # The interactive coordinator uses Terra only after AnyRouter SOL is
    # exhausted.  The Dream job runs in dreamer, whose independent profile
    # keeps micu-api/gpt-5.6-sol as its fallback.
    config["fallback_providers"] = [
        {"provider": "micu-api", "model": "gpt-5.6-terra"}
    ]

    config["terminal"] = {
        **(config.get("terminal") or {}),
        "cwd": str(PROJECT),
    }
    config["skills"] = {
        **(config.get("skills") or {}),
        "external_dirs": [str(PROJECT / "garden/skills")],
        # Garden is the only durable Skill writer. Hermes may read its skills,
        # but automatic post-turn reviews must not create an active local Skill
        # from one conversation.
        "creation_nudge_interval": 0,
        "write_approval": True,
    }
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
    for task in ("title_generation", "approval", "compression", "memory_query_rewrite"):
        auxiliary[task] = {
            **(auxiliary.get(task) or {}),
            "provider": "auto",
            "fallback_chain": [
                {"provider": "micu-api", "model": "gpt-5.6-sol"}
            ],
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
    """Keep the dedicated Dream profile on SOL across both providers."""
    config["model"] = {
        **(config.get("model") or {}),
        "default": "gpt-5.6-sol",
        "provider": "anyrouter",
        "api_mode": "codex_responses",
    }
    config["fallback_providers"] = [
        {"provider": "micu-api", "model": "gpt-5.6-sol"}
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
    config["skills"] = {
        **(config.get("skills") or {}),
        "external_dirs": [str(PROJECT / "garden/skills")],
        "creation_nudge_interval": 0,
        "write_approval": True,
    }
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
    patch_env(HERMES_ENV, {"OPENVIKING_ENDPOINT": "http://127.0.0.1:1933", "OPENVIKING_ACCOUNT": "default", "OPENVIKING_USER": "gwen", "OPENVIKING_AGENT": "hermes"})
    remove_env_keys(HERMES_ENV, {"TERMINAL_CWD", "MESSAGING_CWD"})
    print("Runtime configuration installed; secrets remained outside the project.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
