from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/install_runtime.py"
SPEC = importlib.util.spec_from_file_location("install_runtime", MODULE_PATH)
install_runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(install_runtime)


class HermesConfigTests(unittest.TestCase):
    def test_patch_repairs_anyrouter_models_without_dropping_existing_models(self):
        config = {
            "custom_providers": [
                {
                    "name": "anyrouter",
                    "models": {
                        "gpt-5.6-sol": {"name": "gpt-5.6-sol"},
                        "claude-opus-5": {"0": "c", "name": ""},
                    },
                }
            ]
        }

        patched = install_runtime.patch_hermes_config(copy.deepcopy(config))
        models = install_runtime.provider(patched, "anyrouter")["models"]

        self.assertEqual(models["gpt-5.6-sol"]["name"], "gpt-5.6-sol")
        self.assertEqual(models["claude-opus-5"]["name"], "claude-opus-5")
        self.assertNotIn("0", models["claude-opus-5"])
        self.assertEqual(
            patched["model"],
            {
                "default": "gpt-5.6-sol",
                "provider": "anyrouter",
                "api_mode": "codex_responses",
            },
        )
        self.assertEqual(
            patched["fallback_providers"],
            [{"provider": "micu-api", "model": "gpt-5.6-terra"}],
        )
        self.assertEqual(patched["terminal"]["cwd"], str(install_runtime.PROJECT))
        self.assertEqual(
            patched["skills"]["external_dirs"],
            [str(install_runtime.PROJECT / "garden/skills")],
        )
        self.assertEqual(patched["skills"]["creation_nudge_interval"], 0)
        self.assertTrue(patched["skills"]["write_approval"])
        self.assertEqual(patched["web"]["search_backend"], "ddgs")
        self.assertEqual(patched["web"]["extract_backend"], "tavily")
        self.assertEqual(patched["agent"]["api_max_retries"], 3)
        self.assertEqual(patched["web"]["search_backend"], "ddgs")
        self.assertEqual(patched["web"]["extract_backend"], "tavily")
        self.assertTrue(patched["sessions"]["auto_archive"])
        self.assertEqual(patched["sessions"]["auto_archive_days"], 7)
        self.assertEqual(patched["auxiliary"]["transient_retries"], 0)
        self.assertEqual(
            patched["auxiliary"]["title_generation"]["fallback_chain"],
            [{"provider": "micu-api", "model": "gpt-5.6-sol"}],
        )

    def test_patch_rejects_malformed_unrepaired_models(self):
        config = {
            "custom_providers": [
                {"name": "anyrouter", "models": {}},
                {"name": "broken", "models": {"bad": "not-a-mapping"}},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "broken model bad"):
            install_runtime.patch_hermes_config(config)

    def test_patch_dreamer_profile_keeps_independent_sol_fallback(self):
        patched = install_runtime.patch_dreamer_profile_config({})

        self.assertEqual(
            patched["model"],
            {
                "default": "gpt-5.6-sol",
                "provider": "anyrouter",
                "api_mode": "codex_responses",
            },
        )
        self.assertEqual(
            patched["fallback_providers"],
            [{"provider": "micu-api", "model": "gpt-5.6-sol"}],
        )
        self.assertEqual(patched["agent"]["api_max_retries"], 3)
        self.assertEqual(
            patched["skills"]["external_dirs"],
            [str(install_runtime.PROJECT / "garden/skills")],
        )
        self.assertEqual(patched["skills"]["creation_nudge_interval"], 0)
        self.assertTrue(patched["skills"]["write_approval"])


if __name__ == "__main__":
    unittest.main()
