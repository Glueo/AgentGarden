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
                "default": "gpt-6-astra",
                "provider": "anyrouter",
                "api_mode": "codex_responses",
            },
        )
        self.assertEqual(
            patched["fallback_providers"],
            [
                {
                    "provider": "anyrouter",
                    "model": "gpt-5.6-sol",
                    "api_mode": "codex_responses",
                },
                {"provider": "openai-codex", "model": "gpt-5.6-sol"},
                {"provider": "micu-api", "model": "gpt-5.6-sol"},
            ],
        )
        self.assertEqual(patched["terminal"]["cwd"], str(install_runtime.PROJECT))
        self.assertEqual(patched["skills"]["external_dirs"], [])
        self.assertEqual(patched["skills"]["creation_nudge_interval"], 0)
        self.assertTrue(patched["skills"]["write_approval"])
        self.assertTrue(patched["skills"]["ledger"])
        self.assertFalse(patched["curator"]["enabled"])
        self.assertEqual(patched["web"]["search_backend"], "ddgs")
        self.assertEqual(patched["web"]["extract_backend"], "tavily")
        self.assertEqual(patched["agent"]["api_max_retries"], 5)
        self.assertTrue(patched["sessions"]["auto_archive"])
        self.assertEqual(patched["sessions"]["auto_archive_days"], 7)
        self.assertFalse(patched["sessions"]["auto_prune"])
        self.assertEqual(patched["auxiliary"]["transient_retries"], 0)
        self.assertFalse(patched["auxiliary"]["background_review"]["enabled"])

    def test_delegation_pins_anyrouter_without_inheriting_main_fallbacks(self):
        config = {
            "custom_providers": [{"name": "anyrouter", "models": {}}],
            "delegation": {
                "provider": "micu-api",
                "model": "gpt-5.6-sol",
                "fallback_providers": [{"provider": "micu-api", "model": "gpt-5.6-sol"}],
                "max_concurrent_children": 2,
            },
        }

        patched = install_runtime.patch_hermes_config(config)

        self.assertEqual(patched["delegation"]["provider"], "anyrouter")
        self.assertEqual(patched["delegation"]["model"], "gpt-5.6-sol")
        self.assertEqual(patched["delegation"]["api_mode"], "codex_responses")
        self.assertEqual(patched["delegation"]["fallback_providers"], [])
        self.assertEqual(patched["delegation"]["max_concurrent_children"], 2)

    def test_auxiliary_tasks_do_not_consume_the_main_only_micu_fallback(self):
        config = {"custom_providers": [{"name": "anyrouter", "models": {}}]}

        patched = install_runtime.patch_hermes_config(config)

        for task in install_runtime.AUXILIARY_TASKS:
            self.assertEqual(patched["auxiliary"][task]["provider"], "anyrouter")
            self.assertEqual(patched["auxiliary"][task]["model"], "gpt-5.6-sol")
            self.assertEqual(
                patched["auxiliary"][task]["fallback_chain"],
                [{"provider": "openai-codex", "model": "gpt-5.6-sol"}],
                task,
            )

    def test_goal_judge_has_an_explicit_non_micu_route(self):
        config = {
            "custom_providers": [{"name": "anyrouter", "models": {}}],
            "auxiliary": {"goal_judge": {}},
        }

        patched = install_runtime.patch_hermes_config(config)
        judge = patched["auxiliary"]["goal_judge"]

        self.assertEqual(judge.get("provider"), "anyrouter")
        self.assertEqual(judge.get("model"), "gpt-5.6-sol")
        self.assertEqual(
            judge.get("fallback_chain"),
            [{"provider": "openai-codex", "model": "gpt-5.6-sol"}],
        )

    def test_auxiliary_chain_is_not_shared_state_with_the_main_chain(self):
        patched = install_runtime.patch_hermes_config(
            {"custom_providers": [{"name": "anyrouter", "models": {}}]}
        )

        patched["fallback_providers"][1]["model"] = "mutated"

        self.assertEqual(
            patched["auxiliary"]["approval"]["fallback_chain"][0]["model"],
            "gpt-5.6-sol",
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
        self.assertEqual(set(gpt["models"]), {"gpt-6-astra", "gpt-5.6-sol"})

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


    def test_non_main_profiles_drop_micu_from_fallback_routes(self):
        config = {
            "fallback_providers": [
                {"provider": "micu-api", "model": "gpt-5.6-sol"},
                {"provider": "openai-codex", "model": "gpt-5.6-sol"},
            ],
            "auxiliary": {
                "compression": {
                    "fallback_chain": [
                        {"provider": "micu-api", "model": "gpt-5.6-sol"},
                        {"provider": "openai-codex", "model": "gpt-5.6-sol"},
                    ]
                }
            },
            "delegation": {
                "provider": "anyrouter",
                "model": "gpt-5.6-sol",
                "fallback_providers": [
                    {"provider": "micu-api", "model": "gpt-5.6-sol"},
                    {"provider": "openai-codex", "model": "gpt-5.6-sol"},
                ],
            },
        }

        patched = install_runtime.remove_micu_non_main_routes(config)

        self.assertEqual(
            patched["fallback_providers"],
            [{"provider": "openai-codex", "model": "gpt-5.6-sol"}],
        )
        self.assertEqual(
            patched["auxiliary"]["compression"]["fallback_chain"],
            [{"provider": "openai-codex", "model": "gpt-5.6-sol"}],
        )
        self.assertEqual(
            patched["delegation"]["fallback_providers"],
            [{"provider": "openai-codex", "model": "gpt-5.6-sol"}],
        )

    def test_non_main_profiles_reject_direct_micu_routes(self):
        configs = {
            "main model": {"model": {"provider": "micu-api", "default": "gpt-5.6-sol"}},
            "delegation": {"delegation": {"provider": "micu-api", "model": "gpt-5.6-sol"}},
            "auxiliary": {"auxiliary": {"compression": {"provider": "micu-api", "model": "gpt-5.6-sol"}}},
        }

        for route, config in configs.items():
            with self.subTest(route=route), self.assertRaisesRegex(RuntimeError, "Micu"):
                install_runtime.remove_micu_non_main_routes(config)

    def test_patching_twice_is_idempotent(self):
        config = {
            "custom_providers": [
                {"name": "anyrouter", "api_key": "sk-test", "models": {}}
            ]
        }

        once = install_runtime.patch_hermes_config(copy.deepcopy(config))
        twice = install_runtime.patch_hermes_config(copy.deepcopy(once))

        self.assertEqual(once, twice)

    def test_worker_skill_config_uses_the_shared_root_and_preserves_unrelated_dirs(self):
        config = {
            "skills": {
                "external_dirs": [
                    "/shared/team-skills",
                    str(install_runtime.PROJECT / "garden/skills"),
                    str(install_runtime.HOME / ".hermes/profiles/retired/skills"),
                ]
            }
        }

        patched = install_runtime.patch_skill_config(config, shared_root=True)

        self.assertEqual(
            patched["skills"]["external_dirs"],
            ["/shared/team-skills", str(install_runtime.HERMES_SKILLS)],
        )
        self.assertEqual(patched["skills"]["creation_nudge_interval"], 0)
        self.assertTrue(patched["skills"]["write_approval"])
        self.assertTrue(patched["skills"]["ledger"])
        self.assertFalse(patched["curator"]["enabled"])

    def test_worker_skill_config_disables_background_review(self):
        patched = install_runtime.patch_skill_config({}, shared_root=True)

        self.assertFalse(patched["auxiliary"]["background_review"]["enabled"])


class OpenVikingConfigTests(unittest.TestCase):
    def test_non_ark_legacy_vlm_key_is_not_reused(self):
        existing = {
            "vlm": {
                "provider": "openai",
                "api_key": "camel-key",
                "api_base": "https://api.camel.example/v1",
            }
        }
        self.assertIsNone(install_runtime.approved_vlm_key(existing))

    def test_existing_ark_vlm_key_is_reused(self):
        existing = {
            "vlm": {
                "provider": "volcengine",
                "api_key": "ark-key",
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
            }
        }
        self.assertEqual(install_runtime.approved_vlm_key(existing), "ark-key")

    def test_server_boundary_is_forced_to_local_dev(self):
        existing = {"server": {"host": "0.0.0.0", "auth_mode": "dev", "port": 9999}}
        patched = install_runtime.patch_openviking_config(
            existing,
            vlm_key="ark-key",
            embedding_key="embedding-key",
        )
        self.assertEqual(patched["server"]["host"], "127.0.0.1")
        self.assertEqual(patched["server"]["auth_mode"], "dev")
        self.assertEqual(patched["server"]["cors_origins"], ["http://127.0.0.1:1933"])

    def test_existing_vlm_is_replaced_by_the_fixed_doubao_route(self):
        existing = {
            "server": {"host": "127.0.0.1", "port": 9999, "custom": True},
            "storage": {"workspace": "/existing", "transaction": {"enabled": True}},
            "vlm": {
                "provider": "openai",
                "model": "qwen3.6-plus",
                "credentials": [
                    {"id": "camel-qwen", "model": "qwen3.6-plus"},
                    {"id": "micu-sol", "model": "gpt-5.6-sol"},
                ],
            },
            "custom_section": {"keep": True},
        }
        patched = install_runtime.patch_openviking_config(
            copy.deepcopy(existing),
            vlm_key="ark-key",
            embedding_key="embedding-key",
        )
        self.assertEqual(
            patched["vlm"],
            {
                "provider": "volcengine",
                "api_key": "ark-key",
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                "model": "doubao-seed-2-0-lite-260215",
                "temperature": 0.0,
                "max_retries": 1,
                "max_concurrent": 4,
                "timeout": 180.0,
            },
        )
        self.assertNotIn("qwen", str(patched["vlm"]).lower())
        self.assertNotIn("micu", str(patched["vlm"]).lower())
        self.assertEqual(patched["server"]["port"], 1933)
        self.assertTrue(patched["server"]["custom"])
        self.assertEqual(patched["storage"]["workspace"], "/existing")
        self.assertEqual(patched["storage"]["transaction"], {"enabled": True})
        self.assertEqual(patched["custom_section"], existing["custom_section"])

    def test_empty_config_uses_the_fixed_doubao_wire_id(self):
        patched = install_runtime.patch_openviking_config(
            {},
            vlm_key="ark-key",
            embedding_key="embedding-key",
        )
        self.assertEqual(patched["vlm"]["model"], "doubao-seed-2-0-lite-260215")
        self.assertEqual(patched["vlm"]["api_key"], "ark-key")
        self.assertEqual(
            patched["memory"]["custom_templates_dir"],
            str(install_runtime.PROJECT / "openviking/memory-templates"),
        )

    def test_patching_twice_is_idempotent(self):
        once = install_runtime.patch_openviking_config(
            {},
            vlm_key="ark-key",
            embedding_key="embedding-key",
        )
        twice = install_runtime.patch_openviking_config(
            copy.deepcopy(once),
            vlm_key="ark-key",
            embedding_key="embedding-key",
        )
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
