from __future__ import annotations

import importlib.util
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/tick.py"
SPEC = importlib.util.spec_from_file_location("tick", MODULE_PATH)
tick = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tick)


class TickTests(unittest.TestCase):
    @patch.object(tick, "run_phase")
    def test_syncs_garden_and_checks_only_the_default_cron_profile(self, run_phase):
        run_phase.return_value = 0

        self.assertEqual(tick.main(), 0)

        commands = [call.args[0] for call in run_phase.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[1][-2:], ["cron", "tick"])

    @patch.object(tick, "run_phase")
    def test_failed_sync_does_not_skip_the_independent_cron_phase(self, run_phase):
        run_phase.side_effect = [124, 0]
        self.assertEqual(tick.main(), 124)
        self.assertEqual(run_phase.call_count, 2)

    @patch.object(tick.os, "killpg")
    @patch.object(tick.subprocess, "Popen")
    def test_timeout_kills_the_phase_process_group(self, popen, killpg):
        process = popen.return_value
        process.pid = 123
        process.communicate.side_effect = [subprocess.TimeoutExpired(["cmd"], 1), ("", "")]
        code = tick.run_phase(["cmd"], Path.cwd(), timeout=1)
        self.assertEqual(code, 124)
        killpg.assert_called_once()
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @patch.object(tick.os, "killpg", side_effect=ProcessLookupError)
    @patch.object(tick.subprocess, "Popen")
    def test_timeout_tolerates_child_exit_before_kill(self, popen, killpg):
        process = popen.return_value
        process.pid = 123
        process.communicate.side_effect = [subprocess.TimeoutExpired(["cmd"], 1), ("", "")]
        self.assertEqual(tick.run_phase(["cmd"], Path.cwd(), timeout=1), 124)


if __name__ == "__main__":
    unittest.main()
