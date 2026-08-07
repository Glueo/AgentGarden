#!/usr/bin/env python3
"""Small human-readable health check for the local Agent Garden."""

from __future__ import annotations

import json
import os
import stat
import urllib.request
from pathlib import Path


def http_json(url: str) -> tuple[bool, object]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return 200 <= response.status < 300, json.loads(raw) if raw else {"status": response.status}
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    checks = {}
    checks["project"] = project.is_dir()
    checks["garden"] = (project / "garden/_system/policy.md").is_file()
    config = Path.home() / ".openviking/ov.conf"
    checks["openviking_config_0600"] = config.is_file() and stat.S_IMODE(config.stat().st_mode) == 0o600
    ready, details = http_json("http://127.0.0.1:1933/ready")
    checks["openviking_ready"] = ready
    checks["ready_details"] = details
    checks["hermes_config"] = (Path.home() / ".hermes/config.yaml").is_file()
    checks["runtime_writable"] = os.access(project / ".runtime", os.W_OK)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if all(value for key, value in checks.items() if key != "ready_details") else 1


if __name__ == "__main__":
    raise SystemExit(main())
