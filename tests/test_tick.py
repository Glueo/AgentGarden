from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/tick.py"
SPEC = importlib.util.spec_from_file_location("tick", MODULE_PATH)
tick = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tick)


class TickTests(unittest.TestCase):
    @patch.object(tick.subprocess, "run")
    def test_checks_default_and_dreamer_cron_profiles(self, run):
        run.return_value.returncode = 0

        self.assertEqual(tick.main(), 0)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[1][-2:], ["cron", "tick"])
        self.assertEqual(commands[2][-4:], ["-p", "dreamer", "cron", "tick"])


if __name__ == "__main__":
    unittest.main()
