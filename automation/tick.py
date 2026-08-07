#!/usr/bin/env python3
"""Launchd tick: sync the Garden, then let Hermes evaluate due cron jobs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    sync = subprocess.run([sys.executable, str(project / "automation/sync_garden.py")], cwd=project, check=False)
    hermes = Path.home() / ".local/bin/hermes"
    tick = subprocess.run([str(hermes), "cron", "tick"], cwd=project, check=False)
    return sync.returncode or tick.returncode


if __name__ == "__main__":
    raise SystemExit(main())

