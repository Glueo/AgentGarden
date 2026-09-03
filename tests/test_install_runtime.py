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
        claude = install_runtime.provider(patched, "anyrouter-claude")

        # Character-splayed keys are dropped and ``name`` is reset to the
        # wire id, not the display label the corrupted entry carried.
        self.assertEqual(gpt["models"]["gpt-5.6-sol"]["name"], "gpt-5.6-sol")
        self.assertNotIn("0", gpt["models"]["gpt-5.6-sol"])
        self.assertEqual(claude["models"]["claude-opus-5"]["name"], "claude-opus-5")
        self.assertNotIn("0", claude["models"]["claude-opus-5"])

        # Claude moves off the codex_responses surface, which 404s it.
        self.assertNotIn("claude-opus-5", gpt["models"])
        self.assertEqual(gpt["api_mode"], "codex_responses")
        self.assertEqual(claude["api_mode"], "anthropic_messages")
        self.assertEqual(claude["api_key"], "sk-test")
        self.assertEqual(claude["base_url"], install_runtime.ANYROUTER_BASE_URL)

        # Every AnyRouter model must declare the 1M window, and both entries
        # carry the opt-in the source patch reads.
        for entry in (gpt, claude):
            self.assertTrue(entry["context_1m_beta"])
            for alias, model in entry["models"].items():
                self.assertEqual(model["context_length"], 1_000_000, alias)
        for alias in install_runtime.ANYROUTER_CLAUDE_MODELS:
            self.assertIn(alias, claude["models"])

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
                {
                    "provider": "anyrouter-claude",
                    "model": "claude-opus-5",
                    "api_mode": "anthropic_messages",
                },
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
            "claude-opus-5",
        )

    def test_every_anyrouter_hop_pins_its_api_mode(self):
        """AnyRouter hops must never inherit the chain's chat_completions default.

        A fallback entry defaults to chat_completions and only auto-detects
        anthropic_messages for hosts Hermes knows are Anthropic; anyrouter.top
        is not one. An unpinned Claude hop is therefore sent over the OpenAI
        wire and burns its retries on 404 "当前 API 不支持所选模型" before the
        chain advances -- which reads as the Claude tier being skipped.
        """
        expected = {
            "anyrouter": "codex_responses",
            "anyrouter-claude": "anthropic_messages",
        }
        chains = [
            install_runtime.patch_hermes_config(
                {"custom_providers": [{"name": "anyrouter", "models": {}}]}
            ),
            install_runtime.patch_dreamer_profile_config(
                {"custom_providers": [{"name": "anyrouter", "models": {}}]}
            ),
        ]

        checked = 0
        for config in chains:
            chain = config["fallback_providers"] + [
                entry
                for task in install_runtime.AUXILIARY_TASKS
                for entry in (config.get("auxiliary") or {})
                .get(task, {})
                .get("fallback_chain", [])
            ]
            for entry in chain:
                if entry["provider"] not in expected:
                    continue
                self.assertEqual(
                    entry.get("api_mode"), expected[entry["provider"]], entry
                )
                checked += 1
        self.assertTrue(checked, "no AnyRouter hops were checked")

    def test_patch_rejects_malformed_unrepaired_models(self):
        config = {
            "custom_providers": [
                {"name": "anyrouter", "models": {}},
                {"name": "broken", "models": {"bad": "not-a-mapping"}},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "broken model bad"):
            install_runtime.patch_hermes_config(config)

    def test_patch_dreamer_profile_leads_with_claude(self):
        patched = install_runtime.patch_dreamer_profile_config(
            {"custom_providers": [{"name": "anyrouter", "models": {}}]}
        )

        self.assertEqual(
            patched["model"],
            {
                "default": "claude-fable-5-1",
                "provider": "anyrouter-claude",
                "api_mode": "anthropic_messages",
            },
        )
        self.assertEqual(
            patched["fallback_providers"],
            [
                {
                    "provider": "anyrouter-claude",
                    "model": "claude-opus-5",
                    "api_mode": "anthropic_messages",
                },
                {
                    "provider": "anyrouter",
                    "model": "gpt-5.6-sol",
                    "api_mode": "codex_responses",
                },
                {"provider": "micu-api", "model": "gpt-5.6-sol"},
            ],
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
