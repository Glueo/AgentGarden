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
                    "api_key": "sk-test",
                    "models": {
                        "gpt-5.6-sol": {"0": "c", "1": "l", "name": "gpt-5.6-sol"},
                        "claude-opus-5": {"0": "c", "name": "Claude Opus 5"},
                    },
                }
            ]
        }

        patched = install_runtime.patch_hermes_config(copy.deepcopy(config))
        gpt = install_runtime.provider(patched, "anyrouter")

        # Character-splayed keys are dropped and ``name`` is reset to the
        # wire id, not the display label the corrupted entry carried.
        self.assertEqual(gpt["models"]["gpt-5.6-sol"]["name"], "gpt-5.6-sol")
        self.assertNotIn("0", gpt["models"]["gpt-5.6-sol"])

        # AnyRouter serves GPT only; its Claude models and the retired twin
        # entry are dropped rather than carried on a surface that 404s them.
        self.assertNotIn("claude-opus-5", gpt["models"])
        self.assertEqual(gpt["api_mode"], "codex_responses")
        self.assertNotIn("context_1m_beta", gpt)
        self.assertEqual(
            [item["name"] for item in patched["custom_providers"] if item["name"].startswith("anyrouter")],
            ["anyrouter"],
        )

        for alias, model in gpt["models"].items():
            self.assertEqual(model["context_length"], 1_000_000, alias)

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
            [
                {"provider": "openai-codex", "model": "gpt-5.6-sol-900k"},
                {"provider": "micu-api", "model": "gpt-5.6-terra"},
            ],
        )
        self.assertEqual(patched["terminal"]["cwd"], str(install_runtime.PROJECT))
        self.assertEqual(
            patched["skills"]["external_dirs"],
            [str(install_runtime.DREAMER_SKILLS)],
        )
        self.assertEqual(patched["skills"]["creation_nudge_interval"], 0)
        self.assertTrue(patched["skills"]["write_approval"])
        self.assertEqual(patched["web"]["search_backend"], "ddgs")
        self.assertEqual(patched["web"]["extract_backend"], "tavily")
        self.assertEqual(patched["agent"]["api_max_retries"], 3)
        self.assertTrue(patched["sessions"]["auto_archive"])
        self.assertEqual(patched["sessions"]["auto_archive_days"], 7)
        self.assertEqual(patched["auxiliary"]["transient_retries"], 0)

    def test_auxiliary_tasks_mirror_the_main_fallback_chain(self):
        config = {"custom_providers": [{"name": "anyrouter", "models": {}}]}

        patched = install_runtime.patch_hermes_config(config)

        for task in install_runtime.AUXILIARY_TASKS:
            self.assertEqual(patched["auxiliary"][task]["provider"], "auto")
            self.assertEqual(
                patched["auxiliary"][task]["fallback_chain"],
                patched["fallback_providers"],
                task,
            )

    def test_auxiliary_chain_is_not_shared_state_with_the_main_chain(self):
        patched = install_runtime.patch_hermes_config(
            {"custom_providers": [{"name": "anyrouter", "models": {}}]}
        )

        patched["fallback_providers"][0]["model"] = "mutated"

        self.assertEqual(
            patched["auxiliary"]["approval"]["fallback_chain"][0]["model"],
            "gpt-5.6-sol-900k",
        )

    def test_retired_anyrouter_claude_entry_is_removed(self):
        """A config still carrying the retired twin must converge, not keep it.

        AnyRouter's Claude models never worked in practice and the source
        patch that fed them the 1M opt-in is gone, so an inherited
        ``anyrouter-claude`` entry can only produce failing hops.
        """
        config = {
            "custom_providers": [
                {
                    "name": "anyrouter",
                    "api_key": "sk-test",
                    "context_1m_beta": True,
                    "models": {"gpt-5.6-sol": {}, "claude-opus-5": {}},
                },
                {
                    "name": "anyrouter-claude",
                    "api_key": "sk-test",
                    "context_1m_beta": True,
                    "models": {"claude-opus-5": {}},
                },
            ]
        }

        patched = install_runtime.patch_hermes_config(config)

        names = [item["name"] for item in patched["custom_providers"]]
        self.assertNotIn("anyrouter-claude", names)
        gpt = install_runtime.provider(patched, "anyrouter")
        self.assertNotIn("context_1m_beta", gpt)
        self.assertEqual(list(gpt["models"]), ["gpt-5.6-sol"])

    def test_every_anyrouter_reference_pins_its_api_mode(self):
        """AnyRouter is never left to Hermes' chat_completions default.

        A model or fallback entry defaults to chat_completions unless it pins
        a mode, and anyrouter.top is not a host Hermes auto-detects. An
        unpinned reference is sent over the wrong wire and burns its retries
        on 404 before anything advances. Covers the primary model block, the
        provider entry, and every chain hop, so adding an AnyRouter fallback
        later cannot reintroduce the bug.
        """
        configs = [
            install_runtime.patch_hermes_config(
                {"custom_providers": [{"name": "anyrouter", "models": {}}]}
            ),
            install_runtime.patch_dreamer_profile_config(
                {"custom_providers": [{"name": "anyrouter", "models": {}}]}
            ),
        ]

        checked = 0
        for config in configs:
            references = [
                config["model"],
                install_runtime.provider(config, "anyrouter"),
                *config["fallback_providers"],
                *[
                    entry
                    for task in install_runtime.AUXILIARY_TASKS
                    for entry in (config.get("auxiliary") or {})
                    .get(task, {})
                    .get("fallback_chain", [])
                ],
            ]
            for entry in references:
                if entry.get("provider", entry.get("name")) != "anyrouter":
                    continue
                self.assertEqual(entry.get("api_mode"), "codex_responses", entry)
                checked += 1
        self.assertTrue(checked, "no AnyRouter references were checked")

    def test_patch_rejects_malformed_unrepaired_models(self):
        config = {
            "custom_providers": [
                {"name": "anyrouter", "models": {}},
                {"name": "broken", "models": {"bad": "not-a-mapping"}},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "broken model bad"):
            install_runtime.patch_hermes_config(config)

    def test_patch_dreamer_profile_uses_the_gpt_chain(self):
        patched = install_runtime.patch_dreamer_profile_config(
            {"custom_providers": [{"name": "anyrouter", "models": {}}]}
        )

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
        self.assertEqual(patched["skills"]["external_dirs"], [])
        self.assertEqual(patched["skills"]["creation_nudge_interval"], 0)
        self.assertFalse(patched["skills"]["write_approval"])

    def test_patching_twice_is_idempotent(self):
        config = {
            "custom_providers": [
                {"name": "anyrouter", "api_key": "sk-test", "models": {}}
            ]
        }

        once = install_runtime.patch_hermes_config(copy.deepcopy(config))
        twice = install_runtime.patch_hermes_config(copy.deepcopy(once))

        self.assertEqual(once, twice)

    def test_skill_ownership_preserves_unrelated_external_dirs(self):
        config = {
            "skills": {
                "external_dirs": [
                    "/shared/team-skills",
                    str(install_runtime.PROJECT / "garden/skills"),
                    str(install_runtime.DREAMER_SKILLS),
                ]
            }
        }

        patched = install_runtime.patch_skill_ownership(config, dreamer_owner=False)

        self.assertEqual(
            patched["skills"]["external_dirs"],
            ["/shared/team-skills", str(install_runtime.DREAMER_SKILLS)],
        )


if __name__ == "__main__":
    unittest.main()
