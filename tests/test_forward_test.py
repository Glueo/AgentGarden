from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/forward_test.py"


def load_module(evidence_dir: Path, *, hermes_bin: Path | None = None) -> object:
    os.environ["AGENT_GARDEN_FORWARD_TEST_DIR"] = str(evidence_dir)
    if hermes_bin is not None:
        os.environ["AGENT_GARDEN_HERMES_BIN"] = str(hermes_bin)
    spec = importlib.util.spec_from_file_location("forward_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


SKILL_BODY = textwrap.dedent(
    """\
    ---
    name: {name}
    description: A representative candidate used by the forward-test tests.
    ---

    # Candidate

    Answer with the word READY.
    """
)

SPEC_BODY = {
    "input": "Say READY.",
    "expect_substrings": ["READY"],
    "expect_absent": ["Traceback"],
    "timeout_seconds": 30,
}


def make_skill(root: Path, name: str = "sample-skill", *, spec: dict | None = None) -> Path:
    skill = root / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(SKILL_BODY.format(name=name), encoding="utf-8")
    if spec is not None:
        (skill / "forward-test.json").write_text(json.dumps(spec), encoding="utf-8")
    return skill


def fake_hermes(root: Path, script: str) -> Path:
    """A stand-in for the hermes CLI so tests never make a live model call."""
    path = root / "fake-hermes"
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(script), encoding="utf-8")
    path.chmod(0o755)
    return path


class FormatValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.module = load_module(self.root / "evidence")

    def test_valid_skill_has_no_problems(self):
        skill = make_skill(self.root, spec=SPEC_BODY)
        self.assertEqual(self.module.validate_format(skill), [])

    def test_missing_frontmatter_is_rejected(self):
        skill = make_skill(self.root, spec=SPEC_BODY)
        (skill / "SKILL.md").write_text("# No frontmatter\n", encoding="utf-8")
        self.assertTrue(self.module.validate_format(skill))

    def test_name_must_match_directory(self):
        skill = make_skill(self.root, spec=SPEC_BODY)
        (skill / "SKILL.md").write_text(SKILL_BODY.format(name="other-name"), encoding="utf-8")
        problems = self.module.validate_format(skill)
        self.assertTrue(any("does not match directory" in item for item in problems))

    def test_spec_is_required(self):
        skill = make_skill(self.root)
        with self.assertRaises(RuntimeError):
            self.module.load_spec(skill)

    def test_spec_needs_assertions(self):
        skill = make_skill(self.root, spec={"input": "hi", "expect_substrings": []})
        with self.assertRaises(RuntimeError):
            self.module.load_spec(skill)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.evidence = self.root / "evidence"

    def prepare(self, script: str):
        module = load_module(self.evidence, hermes_bin=fake_hermes(self.root, script))
        # Point every protected path and the sandbox at the temp tree so the
        # test never touches the real Garden or Hermes home.
        module.SANDBOX_ROOT = self.root / "sandbox"
        module.HERMES_CONFIG = self.root / "config.yaml"
        module.DREAMER_SKILLS = self.root / "dreamer-skills"
        module.DREAMER_SKILLS.mkdir(exist_ok=True)
        module.PROJECT_ROOT = self.root / "project"
        (module.PROJECT_ROOT / "garden").mkdir(parents=True, exist_ok=True)
        (module.PROJECT_ROOT / ".runtime").mkdir(parents=True, exist_ok=True)
        (module.PROJECT_ROOT / "garden/note.md").write_text("stable\n", encoding="utf-8")
        module.HERMES_CONFIG.write_text(
            "custom_providers:\n  - name: anyrouter\n    api_key: test-key\n    api_mode: codex_responses\n",
            encoding="utf-8",
        )
        return module

    def test_two_green_runs_pass(self):
        module = self.prepare("print('the answer is READY')\n")
        skill = make_skill(self.root, spec=SPEC_BODY)
        evidence = module.run("sample", skill, runs=2)
        self.assertEqual(evidence["verdict"], "passed")
        self.assertEqual(len(evidence["runs"]), 2)

    def test_single_run_is_not_enough(self):
        module = self.prepare("print('READY')\n")
        skill = make_skill(self.root, spec=SPEC_BODY)
        self.assertEqual(module.verify("sample", skill)["status"], "not-run")
        module.run("sample", skill, runs=2)
        self.assertEqual(module.verify("sample", skill)["status"], "passed")

    def test_missing_expected_substring_fails(self):
        module = self.prepare("print('I refuse')\n")
        skill = make_skill(self.root, spec=SPEC_BODY)
        evidence = module.run("sample", skill, runs=2)
        self.assertEqual(evidence["verdict"], "failed")
        # The first red run short-circuits the rest.
        self.assertEqual(len(evidence["runs"]), 1)

    def test_forbidden_substring_fails(self):
        module = self.prepare("print('READY')\nprint('Traceback (most recent call last)')\n")
        skill = make_skill(self.root, spec=SPEC_BODY)
        self.assertEqual(module.run("sample", skill, runs=2)["verdict"], "failed")

    def test_nonzero_exit_fails(self):
        module = self.prepare("print('READY')\nraise SystemExit(3)\n")
        skill = make_skill(self.root, spec=SPEC_BODY)
        self.assertEqual(module.run("sample", skill, runs=2)["verdict"], "failed")

    def test_write_outside_the_sandbox_fails(self):
        module = self.prepare(
            f"""
            from pathlib import Path
            print('READY')
            Path({str(self.root / "project/garden/leaked.md")!r}).write_text('leak')
            """
        )
        skill = make_skill(self.root, spec=SPEC_BODY)
        evidence = module.run("sample", skill, runs=2)
        self.assertEqual(evidence["verdict"], "failed")
        self.assertIn("garden", evidence["protected_paths_changed"])

    def test_format_problems_skip_live_runs(self):
        module = self.prepare("raise SystemExit('the model should never be called')\n")
        skill = make_skill(self.root, spec=SPEC_BODY)
        (skill / "SKILL.md").write_text("no frontmatter\n", encoding="utf-8")
        evidence = module.run("sample", skill, runs=2)
        self.assertEqual(evidence["verdict"], "failed")
        self.assertEqual(evidence["runs"], [])

    def test_sandbox_is_removed_after_each_run(self):
        module = self.prepare("print('READY')\n")
        skill = make_skill(self.root, spec=SPEC_BODY)
        module.run("sample", skill, runs=2)
        leftovers = list(module.SANDBOX_ROOT.glob("*")) if module.SANDBOX_ROOT.exists() else []
        self.assertEqual(leftovers, [])


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.module = load_module(self.root / "evidence")
        self.skill = make_skill(self.root, spec=SPEC_BODY)
        self.module.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    def write_evidence(self, **overrides):
        evidence = {
            "version": 1,
            "candidate": "sample",
            "skill_path": str(self.skill),
            "skill_sha256": self.module.sha256_file(self.skill / "SKILL.md"),
            "spec_sha256": self.module.sha256_file(self.skill / "forward-test.json"),
            "verdict": "passed",
            "format_problems": [],
            "runs_required": 2,
            "runs": [{"index": 1, "passed": True}, {"index": 2, "passed": True}],
            "protected_paths_changed": [],
            "model": "gpt-5.6-sol",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        evidence.update(overrides)
        self.module.evidence_path("sample").write_text(json.dumps(evidence), encoding="utf-8")

    def test_fresh_matching_evidence_passes(self):
        self.write_evidence()
        self.assertEqual(self.module.verify("sample", self.skill)["status"], "passed")

    def test_edited_skill_invalidates_the_pass(self):
        self.write_evidence()
        (self.skill / "SKILL.md").write_text(
            SKILL_BODY.format(name="sample-skill") + "\nAlso do something else.\n", encoding="utf-8"
        )
        result = self.module.verify("sample", self.skill)
        self.assertEqual(result["status"], "not-run")
        self.assertIn("SKILL.md changed", result["reason"])

    def test_edited_spec_invalidates_the_pass(self):
        self.write_evidence()
        (self.skill / "forward-test.json").write_text(
            json.dumps({**SPEC_BODY, "expect_substrings": ["anything"]}), encoding="utf-8"
        )
        self.assertEqual(self.module.verify("sample", self.skill)["status"], "not-run")

    def test_stale_evidence_expires(self):
        old = datetime.now(timezone.utc) - timedelta(days=self.module.EVIDENCE_MAX_AGE_DAYS + 1)
        self.write_evidence(recorded_at=old.isoformat())
        self.assertEqual(self.module.verify("sample", self.skill)["status"], "not-run")

    def test_forged_verdict_without_passing_runs_is_rejected(self):
        self.write_evidence(runs=[{"index": 1, "passed": True}, {"index": 2, "passed": False}])
        self.assertEqual(self.module.verify("sample", self.skill)["status"], "failed")

    def test_lowered_run_requirement_is_rejected(self):
        self.write_evidence(runs_required=1, runs=[{"index": 1, "passed": True}])
        self.assertEqual(self.module.verify("sample", self.skill)["status"], "failed")

    def test_sandbox_escape_is_rejected(self):
        self.write_evidence(protected_paths_changed=["garden"])
        self.assertEqual(self.module.verify("sample", self.skill)["status"], "failed")

    def test_evidence_for_another_candidate_is_rejected(self):
        self.write_evidence(candidate="something-else")
        self.assertEqual(self.module.verify("sample", self.skill)["status"], "not-run")


if __name__ == "__main__":
    unittest.main()
