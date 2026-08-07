from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "garden/skills/distill-experience/scripts/dream_state.py"
SPEC = importlib.util.spec_from_file_location("dream_state", MODULE_PATH)
dream_state = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(dream_state)


class DreamGateTests(unittest.TestCase):
    def state(self, useful: int, last: datetime | None) -> dict:
        sessions = {str(i): {"useful": True, "consumed": False} for i in range(useful)}
        return {"sessions": sessions, "last_full_dream_at": last.isoformat() if last else None}

    def test_ten_useful_sessions_trigger(self):
        now = datetime.now(timezone.utc)
        result = dream_state.gate(self.state(10, now), now)
        self.assertTrue(result["due"])
        self.assertIn("useful_session_threshold", result["reasons"])

    def test_seven_days_trigger(self):
        now = datetime.now(timezone.utc)
        result = dream_state.gate(self.state(0, now - timedelta(days=7)), now)
        self.assertTrue(result["due"])
        self.assertIn("age_threshold", result["reasons"])

    def test_recent_small_batch_does_not_trigger(self):
        now = datetime.now(timezone.utc)
        self.assertFalse(dream_state.gate(self.state(3, now - timedelta(days=1)), now)["due"])


if __name__ == "__main__":
    unittest.main()
