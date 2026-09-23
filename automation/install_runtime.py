#!/usr/bin/env python3
"""Materialize the Agent Garden OpenViking runtime configuration."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

HOME = Path.home()
PROJECT = Path(__file__).resolve().parents[1]

HERMES_ENV = HOME / ".hermes/.env"
OV_DIR = HOME / ".openviking"
OV_CONFIG = OV_DIR / "ov.conf"
OVCLI_CONFIG = OV_DIR / "ovcli.conf"
OV_DATA = HOME / "Library/Application Support/agent-garden/openviking"


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.agent-garden.bak"))


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
    server.update({"host": "127.0.0.1", "port": 1933, "cors_origins": ["http://127.0.0.1:1933"]})
    server.setdefault("auth_mode", "dev")
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


def patch_env(path: Path, values: dict[str, str], remove: set[str] | None = None) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remove = remove or set()
    keys = set(values) | set(remove)
    kept = [line for line in existing if not any(line.startswith(f"{key}=") for key in keys)]
    kept.extend(f"{key}={value}" for key, value in values.items() if key not in remove)
    write_private(path, "\n".join(kept) + "\n")


def update_openviking_environment(path: Path) -> None:
    """Write Agent Garden's OpenViking identity variables without a peer scope."""
    patch_env(
        path,
        {
            "OPENVIKING_ENDPOINT": "http://127.0.0.1:1933",
            "OPENVIKING_ACCOUNT": "default",
            "OPENVIKING_USER": "gwen",
        },
        remove={"OPENVIKING_AGENT"},
    )


def main() -> int:
    existing_ov = json.loads(OV_CONFIG.read_text(encoding="utf-8")) if OV_CONFIG.exists() else {}
    vlm_key = approved_vlm_key(existing_ov)
    embedding_key = existing_ov.get("embedding", {}).get("dense", {}).get("api_key")
    if not vlm_key or not embedding_key:
        raise RuntimeError("Required OpenViking VLM or embedding API key is missing")

    ov = patch_openviking_config(existing_ov, vlm_key=vlm_key, embedding_key=embedding_key)
    ovcli = {"url": "http://127.0.0.1:1933", "account": "default", "user": "gwen", "timeout": 180}
    OV_DIR.mkdir(parents=True, exist_ok=True)
    OV_DATA.mkdir(parents=True, exist_ok=True)
    backup(OV_CONFIG)
    backup(OVCLI_CONFIG)
    write_private(OV_CONFIG, json.dumps(ov, ensure_ascii=False, indent=2) + "\n")
    write_private(OVCLI_CONFIG, json.dumps(ovcli, ensure_ascii=False, indent=2) + "\n")

    update_openviking_environment(HERMES_ENV)
    print("OpenViking runtime installed; Hermes Desktop configuration was preserved.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
