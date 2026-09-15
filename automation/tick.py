#!/usr/bin/env python3
"""Launchd tick: sync the Garden, then let Hermes evaluate due cron jobs."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

SYNC_TIMEOUT = 900
CRON_TIMEOUT = 600


def run_phase(command: list[str], cwd: Path, *, timeout: int) -> int:
    process = None
    try:
        process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
        process.communicate(timeout=timeout)
        return int(process.returncode or 0)
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        return 124
    except OSError:
        return 127


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    hermes = Path.home() / ".local/bin/hermes"
    phases = (
        ([sys.executable, str(project / "automation/sync_garden.py")], SYNC_TIMEOUT),
        ([str(hermes), "cron", "tick"], CRON_TIMEOUT),
    )
    results = [run_phase(command, project, timeout=timeout) for command, timeout in phases]
    return next((code for code in results if code), 0)


if __name__ == "__main__":
    raise SystemExit(main())
