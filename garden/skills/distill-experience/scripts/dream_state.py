#!/usr/bin/env python3
"""Deterministic gate and cursor for Agent Garden Dream runs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
STATE_PATH = Path(os.environ.get("AGENT_GARDEN_DREAM_STATE", PROJECT_ROOT / ".runtime/dream-state.json"))
SESSION_THRESHOLD = 10
DAY_THRESHOLD = 7


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"version": 1, "last_full_dream_at": None, "sessions": {}, "dreams": []}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.setdefault("version", 1)
    state.setdefault("last_full_dream_at", None)
    state.setdefault("sessions", {})
    state.setdefault("dreams", [])
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def gate(state: dict, at: datetime) -> dict:
    useful = sum(1 for item in state["sessions"].values() if item.get("useful") and not item.get("consumed"))
    last_text = state.get("last_full_dream_at")
    last = datetime.fromisoformat(last_text) if last_text else None
    age_due = last is None or at - last >= timedelta(days=DAY_THRESHOLD)
    return {
        "due": useful >= SESSION_THRESHOLD or age_due,
        "reasons": [reason for reason, applies in (("useful_session_threshold", useful >= SESSION_THRESHOLD), ("age_threshold", age_due)) if applies],
        "new_useful_sessions": useful,
        "session_threshold": SESSION_THRESHOLD,
        "last_full_dream_at": last_text,
        "day_threshold": DAY_THRESHOLD,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    record = sub.add_parser("record")
    record.add_argument("session_key")
    decision = record.add_mutually_exclusive_group(required=True)
    decision.add_argument("--useful", action="store_true")
    decision.add_argument("--not-useful", action="store_true")
    complete = sub.add_parser("complete")
    complete.add_argument("--snapshot", required=True)
    complete.add_argument("--git-commit", required=True)
    args = parser.parse_args()

    state = load_state()
    at = now_utc()
    if args.command == "record":
        state["sessions"].setdefault(args.session_key, {"useful": bool(args.useful), "recorded_at": at.isoformat(), "consumed": False})
        save_state(state)
    elif args.command == "complete":
        consumed = []
        for key, item in state["sessions"].items():
            if item.get("useful") and not item.get("consumed"):
                item["consumed"] = True
                consumed.append(key)
        state["last_full_dream_at"] = at.isoformat()
        state["dreams"].append({"completed_at": at.isoformat(), "snapshot": args.snapshot, "git_commit": args.git_commit, "sessions": consumed})
        save_state(state)
    print(json.dumps(gate(state, at), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
