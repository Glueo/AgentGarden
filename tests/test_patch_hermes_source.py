from __future__ import annotations

import importlib.util
import subprocess
import textwrap
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/patch_hermes_source.py"
SPEC = importlib.util.spec_from_file_location("patch_hermes_source", MODULE_PATH)
patch_hermes_source = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(patch_hermes_source)


MARKER, (RELATIVE, EDITS) = next(iter(patch_hermes_source.PATCHES.items()))


class ApplyPatchTests(unittest.TestCase):
    def source_before_patch(self) -> str:
        """The upstream shape each edit anchors on, in one synthetic module."""
        return "".join(old for old, _ in EDITS)

    def test_applies_every_edit(self):
        patched = patch_hermes_source.apply_patch(
            self.source_before_patch(), MARKER, EDITS
        )

        self.assertIn(MARKER, patched)
        for _, new in EDITS:
            self.assertIn(new, patched)

    def test_is_idempotent(self):
        once = patch_hermes_source.apply_patch(
            self.source_before_patch(), MARKER, EDITS
        )
        twice = patch_hermes_source.apply_patch(once, MARKER, EDITS)

        self.assertEqual(once, twice)

    def test_raises_when_an_anchor_is_missing(self):
        # A silently skipped patch would leave Hermes sending requests the
        # relay rejects, surfacing much later as an opaque provider error.
        with self.assertRaisesRegex(RuntimeError, "matched 0 times"):
            patch_hermes_source.apply_patch("unrelated source", MARKER, EDITS)

    def test_raises_when_an_anchor_is_ambiguous(self):
        doubled = self.source_before_patch() * 2

        with self.assertRaisesRegex(RuntimeError, "matched 2 times"):
            patch_hermes_source.apply_patch(doubled, MARKER, EDITS)


class LiveHermesSourceTests(unittest.TestCase):
    def test_patch_applies_to_the_installed_hermes(self):
        """The anchors must still match the Hermes actually installed here.

        This is the test that fails after an upstream refactor moves the
        code the patch depends on -- exactly when it needs re-checking.
        """
        target = patch_hermes_source.HERMES_SOURCE / RELATIVE
        if not target.exists():
            self.skipTest(f"Hermes source not installed at {target}")

        source = target.read_text(encoding="utf-8")
        if MARKER in source:
            return  # already patched in place

        patched = patch_hermes_source.apply_patch(source, MARKER, EDITS)
        self.assertIn(MARKER, patched)

    def test_patched_hermes_sends_the_1m_beta_to_anyrouter_only(self):
        """The patch must survive Hermes' own base_url normalization.

        ``build_anthropic_client`` strips the ``/v1`` suffix before asking
        for betas, so an opt-in keyed on the configured URL silently never
        fires. Only building the real client catches that -- the string-level
        tests above pass either way. Native Anthropic must stay untouched:
        subscriptions without the long-context beta reject requests carrying
        it, which would break every short auxiliary call.
        """
        root = patch_hermes_source.HERMES_SOURCE
        interpreter = root / ".venv/bin/python"
        if not (root / RELATIVE).exists() or not interpreter.exists():
            self.skipTest("Hermes source or its virtualenv is not installed")

        probe = textwrap.dedent(
            """
            import sys
            sys.path.insert(0, sys.argv[1])
            from agent.anthropic_adapter import build_anthropic_client

            for url in ("https://anyrouter.top/v1", "https://api.anthropic.com"):
                headers = {
                    key.lower(): value
                    for key, value in build_anthropic_client("sk-test", url)
                    .default_headers.items()
                }
                print(url, "context-1m-2025-08-07" in headers.get("anthropic-beta", ""))
            """
        )
        result = subprocess.run(
            [str(interpreter), "-c", probe, str(root)],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = dict(
            line.rsplit(" ", 1) for line in result.stdout.strip().splitlines()
        )
        self.assertEqual(emitted.get("https://anyrouter.top/v1"), "True")
        self.assertEqual(emitted.get("https://api.anthropic.com"), "False")



if __name__ == "__main__":
    unittest.main()
