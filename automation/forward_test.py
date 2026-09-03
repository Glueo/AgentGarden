#!/usr/bin/env python3
"""Isolated forward test for a distilled Skill candidate.

The promotion policy has always required "two independent successes plus an
isolated forward test" before a candidate may become a Skill, but the test
half was never mechanized: ``promotion_gate.py`` accepted
``--skill-validation passed`` as a bare assertion, so the only way to reach
``promote_skill`` was for the Dreamer to vouch for itself. Every Dream so far
has correctly refused to do that, which is why the Skill route has produced
nothing in three runs.

This module makes the test real and, more importantly, makes its *result*
independently checkable: it runs the candidate Skill in a throwaway Hermes
home against a declared representative input, records what happened, and
leaves an evidence file that ``promotion_gate.py`` re-verifies against the
Skill's current bytes. A model can no longer talk its way past the gate; it
can only run the test and let the recorded outcome speak.

Isolation is deliberate on four axes:

* **Skills** — the candidate is copied into a fresh home whose
  ``external_dirs`` is empty, so the run exercises this Skill and not the
  rest of the Dreamer's library.
* **Memory** — the sandbox config omits ``memory.provider`` entirely, so the
  probe cannot read or write OpenViking and cannot contaminate the very
  trajectory store the evidence is drawn from.
* **Filesystem** — the working directory is a scratch tree, and every
  protected path is hashed before and after. A Skill that writes outside its
  sandbox fails the test regardless of what it printed.
* **Secrets** — the sandbox home holds a real provider key, so it is created
  0700, its config 0600, and the whole tree is removed when the run ends.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HOME = Path.home()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(
    os.environ.get("AGENT_GARDEN_FORWARD_TEST_DIR", PROJECT_ROOT / ".runtime/forward-tests")
)
HERMES_BIN = Path(os.environ.get("AGENT_GARDEN_HERMES_BIN", HOME / ".local/bin/hermes"))
HERMES_CONFIG = Path(os.environ.get("AGENT_GARDEN_HERMES_CONFIG", HOME / ".hermes/config.yaml"))
DREAMER_SKILLS = Path(
    os.environ.get("AGENT_GARDEN_DREAMER_SKILLS", HOME / ".hermes/profiles/dreamer/skills")
)
SANDBOX_ROOT = Path(
    os.environ.get("AGENT_GARDEN_FORWARD_TEST_SANDBOX", HOME / ".hermes/forward-test-runs")
)

SPEC_NAME = "forward-test.json"
EVIDENCE_VERSION = 1
# Two clean runs, both green. One run lets an unreliable Skill through on a
# lucky sample; requiring two matches the evidence rule the trajectory side
# already uses ("two independent successes", not "one good one").
DEFAULT_RUNS = 2
DEFAULT_TIMEOUT_SECONDS = 420
# Evidence is a claim about bytes that still exist. Two weeks is long enough
# for a candidate to sit between Dreams and short enough that a stale pass
# never silently authorizes a much later promotion.
EVIDENCE_MAX_AGE_DAYS = 14
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_PROVIDER = "anyrouter"
# Excerpt only. Full transcripts can carry private session content and are not
# the artifact the gate reads; the digest is what makes a run tamper-evident.
EXCERPT_LIMIT = 2000

SKIP_DIR_NAMES = {"__pycache__", ".git", ".obsidian"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def tree_digest(root: Path, *, exclude: tuple[Path, ...] = ()) -> str:
    """Content digest of a directory tree, or of a single file.

    Used as a before/after witness that a probe stayed inside its sandbox, so
    it must cover names as well as bytes: a Skill that deletes a note or adds
    one changes the digest even when no existing file's content moved.
    """
    if root.is_file():
        return sha256_file(root)
    if not root.exists():
        return "absent"
    parts = []
    for path in sorted(root.rglob("*")):
        if any(name in SKIP_DIR_NAMES for name in path.parts):
            continue
        if any(path == item or item in path.parents for item in exclude):
            continue
        if path.is_file():
            parts.append(f"{path.relative_to(root).as_posix()}:{sha256_file(path)}")
    return sha256_text("\n".join(parts))


def protected_paths() -> dict[str, Path]:
    return {
        "garden": PROJECT_ROOT / "garden",
        "runtime": PROJECT_ROOT / ".runtime",
        "dreamer_skills": DREAMER_SKILLS,
        "hermes_config": HERMES_CONFIG,
    }


def protected_digests() -> dict[str, str]:
    # The evidence file itself lands under .runtime; excluding its directory
    # keeps this check about the probe's writes, not our own bookkeeping.
    return {
        name: tree_digest(path, exclude=(EVIDENCE_DIR,))
        for name, path in protected_paths().items()
    }


def evidence_path(candidate: str) -> Path:
    return EVIDENCE_DIR / f"{candidate}.json"


def validate_format(skill_dir: Path) -> list[str]:
    """Structural problems that disqualify a candidate before any model runs.

    Cheap and deterministic on purpose: a malformed Skill should fail here,
    for free, rather than burning two live model runs to discover that its
    frontmatter never parsed.
    """
    problems = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return [f"missing {skill_file}"]
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ["SKILL.md does not open with YAML frontmatter"]
    _, _, rest = text.partition("---\n")
    raw, separator, body = rest.partition("\n---")
    if not separator:
        return ["SKILL.md frontmatter is not terminated"]
    try:
        frontmatter = yaml.safe_load(raw) or {}
    except yaml.YAMLError as error:
        return [f"SKILL.md frontmatter is not valid YAML: {error}"]
    if not isinstance(frontmatter, dict):
        return ["SKILL.md frontmatter is not a mapping"]
    for key in ("name", "description"):
        if not str(frontmatter.get(key) or "").strip():
            problems.append(f"SKILL.md frontmatter is missing {key}")
    name = str(frontmatter.get("name") or "").strip()
    if name and name != skill_dir.name:
        problems.append(f"SKILL.md name '{name}' does not match directory '{skill_dir.name}'")
    if not body.strip():
        problems.append("SKILL.md has no body")
    return problems


def load_spec(skill_dir: Path) -> dict:
    """Read the candidate's declared representative input and assertions.

    The spec lives with the Skill rather than in the Garden because
    ``policy.md`` keeps executable Skills runtime-owned and out of the repo;
    the test that defines a Skill's contract belongs on the same side of that
    line. Its hash is recorded in the evidence so a rewritten spec invalidates
    the pass exactly like a rewritten SKILL.md does.
    """
    path = skill_dir / SPEC_NAME
    if not path.is_file():
        raise RuntimeError(
            f"Missing {path}. A Skill candidate must declare a representative "
            "input and its assertions before it can be forward tested."
        )
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not str(spec.get("input") or "").strip():
        raise RuntimeError(f"{path}: 'input' is required")
    expected = spec.get("expect_substrings") or []
    if not isinstance(expected, list) or not expected:
        raise RuntimeError(f"{path}: 'expect_substrings' must be a non-empty list")
    forbidden = spec.get("expect_absent") or []
    if not isinstance(forbidden, list):
        raise RuntimeError(f"{path}: 'expect_absent' must be a list")
    return {
        "input": str(spec["input"]),
        "expect_substrings": [str(item) for item in expected],
        "expect_absent": [str(item) for item in forbidden],
        "timeout_seconds": int(spec.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        "sha256": sha256_file(path),
    }


def provider_entry(name: str) -> dict:
    config = yaml.safe_load(HERMES_CONFIG.read_text(encoding="utf-8")) or {}
    for item in config.get("custom_providers") or []:
        if item.get("name") == name:
            return item
    raise RuntimeError(f"Hermes provider not found: {name}")


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def build_sandbox(skill_dir: Path, *, model: str, provider: str, stamp: str) -> tuple[Path, Path, Path]:
    """Materialize a throwaway Hermes home holding only the candidate Skill."""
    sandbox = SANDBOX_ROOT / f"{skill_dir.name}-{stamp}"
    home = sandbox / "home"
    work = sandbox / "work"
    for directory in (sandbox, home, work):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    shutil.copytree(skill_dir, home / "skills" / skill_dir.name, dirs_exist_ok=True)
    entry = provider_entry(provider)
    config = {
        "model": {
            "default": model,
            "provider": provider,
            "api_mode": entry.get("api_mode", "codex_responses"),
        },
        "custom_providers": [entry],
        # Empty external_dirs is the point of the sandbox: the Dreamer's other
        # Skills must not be loadable, or a candidate could pass by leaning on
        # behavior that lives somewhere else.
        "skills": {"external_dirs": [], "creation_nudge_interval": 0, "write_approval": True},
        "agent": {"api_max_retries": 2},
        # No `memory` key: the probe must not reach OpenViking.
    }
    write_private(home / "config.yaml", yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    return sandbox, home, work


def sandbox_env(home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("OPENVIKING_")}
    env["HERMES_HOME"] = str(home)
    env["NO_COLOR"] = "1"
    return env


def evaluate_output(output: str, spec: dict) -> dict:
    lowered = output.lower()
    missing = [item for item in spec["expect_substrings"] if item.lower() not in lowered]
    present = [item for item in spec["expect_absent"] if item.lower() in lowered]
    return {"missing": missing, "forbidden_present": present}


def run_once(
    *,
    index: int,
    skill_dir: Path,
    spec: dict,
    model: str,
    provider: str,
    stamp: str,
) -> dict:
    sandbox, home, work = build_sandbox(skill_dir, model=model, provider=provider, stamp=f"{stamp}-{index}")
    command = [
        str(HERMES_BIN),
        "--in", str(work),
        "-m", model,
        "--provider", provider,
        "-s", skill_dir.name,
        "--accept-hooks",
        "--yolo",
        "-z", spec["input"],
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=work,
            env=sandbox_env(home),
            capture_output=True,
            text=True,
            timeout=spec["timeout_seconds"],
            check=False,
        )
        output = completed.stdout + completed.stderr
        exit_code = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + (error.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        exit_code = -1
        timed_out = True
    finally:
        duration = time.monotonic() - started
        # The sandbox home carries a live provider key; it does not outlive
        # the run even when the run raised.
        shutil.rmtree(sandbox, ignore_errors=True)
    checks = evaluate_output(output, spec)
    return {
        "index": index,
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 1),
        "output_sha256": sha256_text(output),
        "output_excerpt": output[-EXCERPT_LIMIT:],
        **checks,
        "passed": exit_code == 0 and not timed_out and not checks["missing"] and not checks["forbidden_present"],
    }


def run(
    candidate: str,
    skill_dir: Path,
    *,
    runs: int = DEFAULT_RUNS,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    problems = validate_format(skill_dir)
    spec = load_spec(skill_dir) if not problems else None
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    before = protected_digests()
    executed: list[dict] = []
    if not problems:
        for index in range(1, runs + 1):
            result = run_once(
                index=index,
                skill_dir=skill_dir,
                spec=spec,
                model=model,
                provider=provider,
                stamp=stamp,
            )
            executed.append(result)
            # Stop at the first red run: the verdict cannot recover, and a
            # second live call would only spend tokens to restate it.
            if not result["passed"]:
                break
    after = protected_digests()
    changed = sorted(name for name, value in before.items() if after.get(name) != value)
    passed = (
        not problems
        and not changed
        and len(executed) == runs
        and all(item["passed"] for item in executed)
    )
    evidence = {
        "version": EVIDENCE_VERSION,
        "candidate": candidate,
        "skill_path": str(skill_dir),
        "skill_sha256": sha256_file(skill_dir / "SKILL.md") if (skill_dir / "SKILL.md").is_file() else None,
        "spec_sha256": spec["sha256"] if spec else None,
        "verdict": "passed" if passed else "failed",
        "format_problems": problems,
        "runs_required": runs,
        "runs": executed,
        "protected_paths_changed": changed,
        "model": model,
        "provider": provider,
        "recorded_at": now_utc().isoformat(),
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = evidence_path(candidate)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return evidence


def verify(candidate: str, skill_dir: Path | None = None, *, at: datetime | None = None) -> dict:
    """Re-derive a validation status from recorded evidence.

    ``promotion_gate.py`` calls this instead of believing a caller's claim.
    Every rejection reason is returned rather than collapsed to a boolean so
    the Dream audit can say precisely why a Skill did not promote.
    """
    at = at or now_utc()
    path = evidence_path(candidate)
    if not path.is_file():
        return {"status": "not-run", "reason": f"no forward-test evidence at {path}"}
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"status": "not-run", "reason": f"unreadable forward-test evidence: {error}"}
    if evidence.get("candidate") != candidate:
        return {"status": "not-run", "reason": "evidence belongs to a different candidate"}
    if evidence.get("verdict") != "passed":
        return {"status": "failed", "reason": "recorded verdict is not passed"}
    if int(evidence.get("runs_required") or 0) < DEFAULT_RUNS:
        return {"status": "failed", "reason": f"fewer than {DEFAULT_RUNS} required runs"}
    runs = evidence.get("runs") or []
    if len(runs) < int(evidence.get("runs_required") or 0) or not all(item.get("passed") for item in runs):
        return {"status": "failed", "reason": "not every required run passed"}
    if evidence.get("protected_paths_changed"):
        return {"status": "failed", "reason": "the probe wrote outside its sandbox"}
    recorded_at = evidence.get("recorded_at")
    try:
        recorded = datetime.fromisoformat(recorded_at)
    except (TypeError, ValueError):
        return {"status": "not-run", "reason": "evidence has no usable timestamp"}
    if at - recorded > timedelta(days=EVIDENCE_MAX_AGE_DAYS):
        return {"status": "not-run", "reason": f"evidence is older than {EVIDENCE_MAX_AGE_DAYS} days"}
    target = Path(skill_dir or evidence.get("skill_path") or "")
    skill_file = target / "SKILL.md"
    if not skill_file.is_file():
        return {"status": "not-run", "reason": f"tested skill is missing at {skill_file}"}
    # The pass belongs to the bytes that were tested. Editing SKILL.md after a
    # green run silently invalidates it, which is the whole reason the hash is
    # recorded rather than just the path.
    if sha256_file(skill_file) != evidence.get("skill_sha256"):
        return {"status": "not-run", "reason": "SKILL.md changed since the forward test"}
    spec_file = target / SPEC_NAME
    if not spec_file.is_file() or sha256_file(spec_file) != evidence.get("spec_sha256"):
        return {"status": "not-run", "reason": f"{SPEC_NAME} changed since the forward test"}
    return {
        "status": "passed",
        "reason": "forward test passed",
        "recorded_at": recorded_at,
        "runs": len(runs),
        "model": evidence.get("model"),
    }


def summarize(evidence: dict) -> dict:
    return {
        "candidate": evidence["candidate"],
        "verdict": evidence["verdict"],
        "skill_path": evidence["skill_path"],
        "skill_sha256": evidence["skill_sha256"],
        "runs_required": evidence["runs_required"],
        "runs_passed": sum(1 for item in evidence["runs"] if item["passed"]),
        "format_problems": evidence["format_problems"],
        "protected_paths_changed": evidence["protected_paths_changed"],
        "failures": [
            {
                "index": item["index"],
                "exit_code": item["exit_code"],
                "timed_out": item["timed_out"],
                "missing": item["missing"],
                "forbidden_present": item["forbidden_present"],
            }
            for item in evidence["runs"]
            if not item["passed"]
        ],
        "evidence_path": str(evidence_path(evidence["candidate"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="Forward test a Skill candidate in isolation")
    run_parser.add_argument("candidate")
    run_parser.add_argument("--skill", required=True, help="Path to the candidate Skill directory")
    run_parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    run_parser.add_argument("--model", default=DEFAULT_MODEL)
    run_parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    verify_parser = sub.add_parser("verify", help="Re-check recorded evidence against the Skill on disk")
    verify_parser.add_argument("candidate")
    verify_parser.add_argument("--skill")
    args = parser.parse_args()

    if args.command == "run":
        if args.runs < DEFAULT_RUNS:
            print(
                json.dumps(
                    {"error": f"--runs must be at least {DEFAULT_RUNS}"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        skill_dir = Path(args.skill).expanduser().resolve()
        evidence = run(
            args.candidate,
            skill_dir,
            runs=args.runs,
            model=args.model,
            provider=args.provider,
        )
        print(json.dumps(summarize(evidence), ensure_ascii=False, indent=2))
        return 0 if evidence["verdict"] == "passed" else 1

    skill_dir = Path(args.skill).expanduser().resolve() if args.skill else None
    result = verify(args.candidate, skill_dir)
    print(json.dumps({"candidate": args.candidate, **result}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
