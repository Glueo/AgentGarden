from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/promotion_gate.py"
SPEC = importlib.util.spec_from_file_location("promotion_gate", MODULE_PATH)
promotion_gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(promotion_gate)


class PromotionGateTests(unittest.TestCase):
    def candidate(self, *observations):
        return {"observations": [{"trajectory": uri, "outcome": outcome} for uri, outcome in observations]}

    def test_one_success_stays_provisional(self):
        result = promotion_gate.decision(self.candidate(("viking://trace/one", "success")))
        self.assertEqual(result["route"], "provisional_experience")

    def test_duplicate_uri_is_not_independent(self):
        result = promotion_gate.decision(self.candidate(("viking://trace/one", "success"), ("viking://trace/one", "success")), skill_validation="passed")
        self.assertEqual(result["route"], "provisional_experience")

    def test_two_successes_need_skill_validation(self):
        evidence = self.candidate(("viking://trace/one", "success"), ("viking://trace/two", "success"))
        self.assertEqual(promotion_gate.decision(evidence)["route"], "validated_experience")
        self.assertEqual(promotion_gate.decision(evidence, skill_validation="passed")["route"], "promote_skill")

    def test_conflict_always_routes_review(self):
        evidence = self.candidate(("viking://trace/one", "success"), ("viking://trace/two", "success"))
        self.assertEqual(promotion_gate.decision(evidence, conflict=True, skill_validation="passed")["route"], "review")

    def test_high_risk_always_routes_review(self):
        evidence = self.candidate(("viking://trace/one", "success"), ("viking://trace/two", "success"))
        self.assertEqual(promotion_gate.decision(evidence, risk="mandatory-review", skill_validation="passed")["route"], "review")

    def test_two_independent_successes_are_event_ready(self):
        candidate = self.candidate(
            ("viking://trace/one", "success"),
            ("viking://trace/two", "success"),
        )
        self.assertTrue(promotion_gate.readiness(candidate)["ready"])

    def test_duplicate_success_is_not_event_ready(self):
        candidate = self.candidate(
            ("viking://trace/one", "success"),
            ("viking://trace/one", "success"),
        )
        self.assertFalse(promotion_gate.readiness(candidate)["ready"])

    def test_resolved_candidate_waits_for_new_success(self):
        candidate = self.candidate(
            ("viking://trace/one", "success"),
            ("viking://trace/two", "success"),
        )
        promotion_gate.resolve_candidate(
            candidate,
            "validated_experience",
            at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        self.assertFalse(promotion_gate.readiness(candidate)["ready"])

        candidate["observations"].append(
            {"trajectory": "viking://trace/three", "outcome": "success"}
        )
        self.assertTrue(promotion_gate.readiness(candidate)["ready"])

    def test_ready_candidates_only_returns_unhandled_clusters(self):
        state = {
            "candidates": {
                "ready": self.candidate(
                    ("viking://trace/one", "success"),
                    ("viking://trace/two", "success"),
                ),
                "waiting": self.candidate(("viking://trace/three", "success")),
            }
        }
        self.assertEqual(
            [item["candidate"] for item in promotion_gate.ready_candidates(state)],
            ["ready"],
        )


if __name__ == "__main__":
    unittest.main()
