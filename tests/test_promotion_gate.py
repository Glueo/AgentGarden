from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "garden/skills/distill-experience/scripts/promotion_gate.py"
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


if __name__ == "__main__":
    unittest.main()
