#!/usr/bin/env python3
"""Evidence-based promotion gate; never relies on model confidence."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(os.environ.get("AGENT_GARDEN_PROMOTION_STATE", PROJECT_ROOT / ".runtime/promotion-candidates.json"))
STATE_VERSION = 2
ROUTES = ("provisional_experience", "validated_experience", "promote_skill", "review")
SKILL_VALIDATION_STATES = ("not-run", "passed", "failed")


def forward_test_module():
    """Load the forward-test harness by path.

    Same lazy path-import install_runtime uses for its source patches: the
    automation scripts are executed as files, not imported as a package, so a
    plain sibling import does not resolve under the test runner.
    """
    spec = importlib.util.spec_from_file_location(
        "forward_test", PROJECT_ROOT / "automation/forward_test.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def skill_validation_for(candidate: str, skill_dir: str | None) -> dict:
    """Derive a validation status from recorded forward-test evidence.

    The gate deliberately does not accept "passed" from its caller. Promotion
    to a Skill is the one route that changes what every worker executes, so it
    must rest on a re-checkable artifact — an evidence file whose recorded
    hash still matches the SKILL.md on disk — rather than on the judgment of
    the same model that wrote the Skill.
    """
    try:
        module = forward_test_module()
    except Exception as error:  # pragma: no cover - only a broken checkout
        return {"status": "not-run", "reason": f"forward-test harness unavailable: {error}"}
    return module.verify(candidate, Path(skill_dir) if skill_dir else None)


def successful_trajectories(candidate: dict) -> list[str]:
    return sorted({
        item["trajectory"]
        for item in candidate.get("observations", [])
        if item.get("outcome") == "success"
    })


def new_candidate() -> dict:
    return {
        "observations": [],
        "handled_success_count": 0,
        "last_route": None,
    }


def normalize_candidate(candidate: dict, *, legacy: bool = False) -> dict:
    candidate.setdefault("observations", [])
    if "handled_success_count" not in candidate:
        # Version-1 candidates were already considered by the old periodic
        # Dream workflow. Mark their existing evidence handled so the version
        # upgrade cannot replay stale promotions as fresh event triggers.
        candidate["handled_success_count"] = (
            len(successful_trajectories(candidate)) if legacy else 0
        )
    candidate.setdefault("last_route", None)
    return candidate


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"version": STATE_VERSION, "candidates": {}}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    legacy = int(state.get("version", 1)) < STATE_VERSION
    state["version"] = STATE_VERSION
    state.setdefault("candidates", {})
    for candidate in state["candidates"].values():
        normalize_candidate(candidate, legacy=legacy)
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def readiness(candidate: dict) -> dict:
    successes = successful_trajectories(candidate)
    handled = int(candidate.get("handled_success_count", 0))
    return {
        "ready": len(successes) >= 2 and len(successes) > handled,
        "independent_successes": len(successes),
        "handled_success_count": handled,
        "new_successes": max(0, len(successes) - handled),
    }


def ready_candidates(state: dict) -> list[dict]:
    ready = []
    for name, candidate in sorted(state.get("candidates", {}).items()):
        status = readiness(candidate)
        if status["ready"]:
            ready.append({"candidate": name, **status})
    return ready


def resolve_candidate(candidate: dict, route: str, *, at: datetime | None = None) -> dict:
    if route not in ROUTES:
        raise ValueError(f"Unsupported route: {route}")
    normalize_candidate(candidate)
    candidate["handled_success_count"] = len(successful_trajectories(candidate))
    candidate["last_route"] = route
    candidate["resolved_at"] = (at or datetime.now(timezone.utc)).isoformat()
    return candidate


def decision(
    candidate: dict,
    *,
    conflict: bool = False,
    risk: str = "normal",
    skill_validation: str = "not-run",
    skill_validation_reason: str | None = None,
) -> dict:
    successes = successful_trajectories(candidate)
    failures = sorted({item["trajectory"] for item in candidate.get("observations", []) if item.get("outcome") == "failure"})
    if skill_validation not in SKILL_VALIDATION_STATES:
        raise ValueError(f"Unsupported skill validation state: {skill_validation}")
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
        "skill_validation_reason": skill_validation_reason,
        "conflict": conflict,
        "risk": risk,
        "event": readiness(candidate),
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
    # There is deliberately no ``--skill-validation passed``. The only way to
    # reach ``promote_skill`` is to point the gate at a Skill directory whose
    # recorded forward test it can re-verify itself.
    evaluate.add_argument("--skill", help="Candidate Skill directory to re-verify forward-test evidence against")
    sub.add_parser("ready")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("candidate")
    resolve.add_argument("--route", choices=ROUTES, required=True)
    args = parser.parse_args()

    state = load_state()
    if args.command == "observe":
        candidate = state["candidates"].setdefault(args.candidate, new_candidate())
        normalize_candidate(candidate)
        key = (args.trajectory, args.outcome)
        existing = {(item["trajectory"], item["outcome"]) for item in candidate["observations"]}
        if key not in existing:
            candidate["observations"].append({"trajectory": args.trajectory, "outcome": args.outcome, "recorded_at": datetime.now(timezone.utc).isoformat()})
            save_state(state)
        result = decision(candidate)
        output = {"candidate": args.candidate, **result}
    elif args.command == "evaluate":
        candidate = state["candidates"].setdefault(args.candidate, new_candidate())
        normalize_candidate(candidate)
        validation = skill_validation_for(args.candidate, args.skill)
        result = decision(
            candidate,
            conflict=args.conflict,
            risk=args.risk,
            skill_validation=validation["status"],
            skill_validation_reason=validation["reason"],
        )
        output = {"candidate": args.candidate, **result}
    elif args.command == "ready":
        candidates = ready_candidates(state)
        output = {"ready": bool(candidates), "candidates": candidates}
    else:
        candidate = state["candidates"].get(args.candidate)
        if candidate is None:
            print(json.dumps({"error": f"Unknown candidate: {args.candidate}"}, ensure_ascii=False, indent=2))
            return 1
        resolve_candidate(candidate, args.route)
        save_state(state)
        output = {
            "candidate": args.candidate,
            "route": args.route,
            "event": readiness(candidate),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
