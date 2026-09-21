from __future__ import annotations

import plistlib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLIST_PATH = PROJECT_ROOT / "launchd/com.agent-garden.sync.plist"
PYTHON = "/opt/homebrew/Caskroom/miniconda/base/envs/agent-garden/bin/python"
SYNC_SCRIPT = str(PROJECT_ROOT / "automation/sync_garden.py")


class SyncLaunchAgentTests(unittest.TestCase):
    def test_sync_agent_runs_only_garden_sync_every_fifteen_minutes(self):
        self.assertTrue(PLIST_PATH.is_file())
        payload = plistlib.loads(PLIST_PATH.read_bytes())

        self.assertEqual(payload["Label"], "com.agent-garden.sync")
        self.assertEqual(payload["ProgramArguments"], [PYTHON, SYNC_SCRIPT])
        self.assertEqual(payload["StartInterval"], 900)
        self.assertIs(payload["RunAtLoad"], True)
        self.assertEqual(payload["WorkingDirectory"], str(PROJECT_ROOT))
        self.assertNotIn("cron", " ".join(payload["ProgramArguments"]))


if __name__ == "__main__":
    unittest.main()
