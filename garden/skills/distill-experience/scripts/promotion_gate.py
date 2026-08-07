#!/usr/bin/env python3
"""Evidence-based promotion gate; never relies on model confidence."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
STATE_PATH = Path(os.environ.get("AGENT_GARDEN_PROMOTION_STATE", PROJECT_ROOT / ".runtime/promotion-candidates.json"))


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"version": 1, "candidates": {}}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.setdefault("version", 1)
    state.setdefault("candidates", {})
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def decision(candidate: dict, *, conflict: bool = False, risk: str = "normal", skill_validation: str = "not-run") -> dict:
    successes = sorted({item["trajectory"] for item in candidate.get("observations", []) if item.get("outcome") == "success"})
    failures = sorted({item["trajectory"] for item in candidate.get("observations", []) if item.get("outcome") == "failure"})
    if conflict or risk == "mandatory-review":
        route = "review"
    elif len(successes) < 2:
        route = "provisional_experience"
    elif skill_validation != "passed":
        route = "validated_experience"
    else:
        route = "promote_skill"
    return {
        "route": route,
        "independent_successes": len(successes),
        "success_trajectories": successes,
        "failure_trajectories": failures,
        "skill_validation": skill_validation,
        "conflict": conflict,
        "risk": risk,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    observe = sub.add_parser("observe")
    observe.add_argument("candidate")
    observe.add_argument("--trajectory", required=True)
    observe.add_argument("--outcome", choices=("success", "failure"), required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("candidate")
    evaluate.add_argument("--conflict", action="store_true")
    evaluate.add_argument("--risk", choices=("normal", "mandatory-review"), default="normal")
    evaluate.add_argument("--skill-validation", choices=("not-run", "passed", "failed"), default="not-run")
    args = parser.parse_args()

    state = load_state()
    candidate = state["candidates"].setdefault(args.candidate, {"observations": []})
    if args.command == "observe":
        key = (args.trajectory, args.outcome)
        existing = {(item["trajectory"], item["outcome"]) for item in candidate["observations"]}
        if key not in existing:
            candidate["observations"].append({"trajectory": args.trajectory, "outcome": args.outcome, "recorded_at": datetime.now(timezone.utc).isoformat()})
            save_state(state)
        result = decision(candidate)
    else:
        result = decision(candidate, conflict=args.conflict, risk=args.risk, skill_validation=args.skill_validation)
    print(json.dumps({"candidate": args.candidate, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

