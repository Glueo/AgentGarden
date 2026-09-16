from __future__ import annotations

import copy
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/install_runtime.py"
SPEC = importlib.util.spec_from_file_location("install_runtime", MODULE_PATH)
install_runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(install_runtime)


class HermesConfigTests(unittest.TestCase):
    def test_backup_keeps_one_latest_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("first", encoding="utf-8")
            install_runtime.backup(path)
            path.write_text("second", encoding="utf-8")
            install_runtime.backup(path)

            backups = list(path.parent.glob("config.yaml.agent-garden*.bak"))
            self.assertEqual(backups, [path.with_name("config.yaml.agent-garden.bak")])
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "second")

    def test_patch_removes_retired_anyrouter_sol_model(self):
        config = {
            "model": {
                "default": "user-selected-model",
                "provider": "user-selected-provider",
                "api_mode": "user-selected-mode",
                "base_url": "https://user-selected.example/v1",
                "context_length": 123456,
            },
            "custom_providers": [
                {
                    "name": "anyrouter",
                    "api_key": "sk-test",
                    "models": {
                        "gpt-5.6-sol": {"0": "c", "1": "l", "name": "gpt-5.6-sol"},
                        "claude-opus-5": {"0": "c", "name": "Claude Opus 5"},
                    },
                    "extra_body": {
                        "include": [],
                        "metadata": {"preserve": True},
                    },
                },
                {"name": "micu-api", "models": {"gpt-5.6-sol": {"name": "gpt-5.6-sol"}}},
                {"name": "camel", "models": {"qwen3.8-max": {"name": "qwen-3.8-max"}}},
            ]
        }

        patched = install_runtime.patch_hermes_config(copy.deepcopy(config))
        gpt = install_runtime.provider(patched, "anyrouter")

        # AnyRouter no longer serves SOL, and never served Claude reliably.
        # Retired models must be removed even when a stale config still has
        # malformed metadata for them.
        self.assertNotIn("gpt-5.6-sol", gpt["models"])
        self.assertNotIn("claude-opus-5", gpt["models"])
        self.assertEqual(gpt["models"], {})
        self.assertEqual(gpt["api_mode"], "codex_responses")
        self.assertEqual(
            gpt["extra_body"],
            {
                "include": ["reasoning.encrypted_content"],
                "metadata": {"preserve": True},
            },
        )
        self.assertNotIn("context_1m_beta", gpt)
        self.assertNotIn("api_key", gpt)
        self.assertEqual(gpt["key_env"], "ANYROUTER_API_KEY")
        self.assertEqual(
            [item["name"] for item in patched["custom_providers"] if item["name"].startswith("anyrouter")],
            ["anyrouter"],
        )
        self.assertIn("camel", [item["name"] for item in patched["custom_providers"]])
        self.assertIn("micu-api", [item["name"] for item in patched["custom_providers"]])

        self.assertNotIn("model", gpt)
        self.assertEqual(patched["model"], config["model"])
        self.assertFalse(any("fallback" in key.lower() for key in patched))
        coderapi = patched["providers"]["coderapi"]
        self.assertEqual(coderapi["api"], "https://wcf.coderapi.vip/v1")
        self.assertEqual(coderapi["key_env"], "CODERAPI_API_KEY")
        self.assertEqual(coderapi["transport"], "chat_completions")
        self.assertEqual(coderapi["default_model"], "codex-auto-review-openai-compact")
        self.assertNotIn("api_key", coderapi)
        self.assertEqual(patched["terminal"]["cwd"], str(install_runtime.PROJECT))
        self.assertEqual(patched["skills"]["external_dirs"], [])
        self.assertNotIn("creation_nudge_interval", patched["skills"])
        self.assertTrue(patched["skills"]["write_approval"])
        self.assertTrue(patched["skills"]["ledger"])
        self.assertNotIn("curator", patched)
        self.assertEqual(patched["web"]["search_backend"], "ddgs")
        self.assertEqual(patched["web"]["extract_backend"], "tavily")
        self.assertEqual(patched["agent"]["api_max_retries"], 5)
        self.assertTrue(patched["sessions"]["auto_archive"])
        self.assertEqual(patched["sessions"]["auto_archive_days"], 7)
        self.assertFalse(patched["sessions"]["auto_prune"])
        self.assertNotIn("transient_retries", patched["auxiliary"])
        self.assertEqual(patched["auxiliary"]["stream_only_base_urls"], ["wcf.coderapi.vip"])

    def test_delegation_inherits_the_single_main_route(self):
        config = {
            "custom_providers": [{"name": "anyrouter", "models": {}}],
            "delegation": {
                "provider": "micu-api",
                "model": "gpt-5.6-sol",
                "base_url": "https://stale.example/v1",
                "api_key": "stale-key",
                "api_mode": "chat_completions",
                "fallback_providers": [{"provider": "micu-api", "model": "gpt-5.6-sol"}],
                "max_concurrent_children": 2,
            },
        }

        patched = install_runtime.patch_hermes_config(config)

        for key in ("provider", "model", "base_url", "api_key", "api_mode", "fallback_providers"):
            self.assertNotIn(key, patched["delegation"])
        self.assertEqual(patched["delegation"]["max_concurrent_children"], 2)

    def test_missing_anyrouter_does_not_force_a_main_provider(self):
        config = {
            "model": {"default": "chosen", "provider": "manual"},
            "custom_providers": [{"name": "manual", "models": {"chosen": {}}}],
        }

        patched = install_runtime.patch_hermes_config(copy.deepcopy(config))

        self.assertEqual(patched["model"], config["model"])
        self.assertEqual(patched["custom_providers"], config["custom_providers"])

    def test_every_auxiliary_task_uses_coderapi_without_fallback(self):
        config = {
            "custom_providers": [{"name": "anyrouter", "models": {}}],
            "auxiliary": {
                "plugin_registered_task": {"provider": "old", "model": "old"},
                "stream_only_base_urls": ["existing.example"],
            },
        }

        patched = install_runtime.patch_hermes_config(config)

        for task in (*install_runtime.AUXILIARY_TASKS, "plugin_registered_task"):
            route = patched["auxiliary"][task]
            self.assertEqual(route["provider"], "coderapi")
            self.assertEqual(route["model"], "codex-auto-review-openai-compact")
            self.assertNotIn("base_url", route)
            self.assertNotIn("api_key", route)
            self.assertNotIn("api_mode", route)
            self.assertNotIn("fallback_chain", route, task)
        self.assertEqual(
            patched["auxiliary"]["stream_only_base_urls"],
            ["existing.example", "wcf.coderapi.vip"],
        )

    def test_coderapi_key_is_migrated_or_required(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            inline = {"providers": {"coderapi": {"api_key": "inline-test-key"}}}
            with mock.patch.dict(os.environ, {"CODERAPI_API_KEY": ""}):
                self.assertEqual(
                    install_runtime.required_coderapi_key(inline, env_path),
                    "inline-test-key",
                )

                env_path.write_text("CODERAPI_API_KEY=env-test-key\n", encoding="utf-8")
                self.assertEqual(
                    install_runtime.required_coderapi_key({}, env_path),
                    "env-test-key",
                )

                env_path.unlink()
                with self.assertRaisesRegex(RuntimeError, "CODERAPI_API_KEY"):
                    install_runtime.required_coderapi_key({}, env_path)

    def test_goal_judge_has_an_explicit_coderapi_route(self):
        config = {
            "custom_providers": [{"name": "anyrouter", "models": {}}],
            "auxiliary": {"goal_judge": {}},
        }

        patched = install_runtime.patch_hermes_config(config)
        judge = patched["auxiliary"]["goal_judge"]

        self.assertEqual(judge.get("provider"), "coderapi")
        self.assertEqual(judge.get("model"), "codex-auto-review-openai-compact")
        self.assertNotIn("fallback_chain", judge)

    def test_all_fallback_settings_are_removed_recursively(self):
        patched = install_runtime.patch_hermes_config(
            {
                "custom_providers": [{"name": "anyrouter", "models": {}}],
                "fallback_model": {"provider": "old", "model": "old"},
                "fallback_models": ["old"],
                "fallback_providers": [{"provider": "old", "model": "old"}],
                "delegation": {
                    "fallback_providers": [{"provider": "old", "model": "old"}],
                },
                "auxiliary": {
                    "approval": {
                        "fallback_chain": [{"provider": "old", "model": "old"}],
                    },
                    "custom_nested": {"fallback_model": "old"},
                },
            }
        )

        def fallback_paths(value, path=()):
            if isinstance(value, dict):
                for key, nested in value.items():
                    if "fallback" in key.lower():
                        yield ".".join((*path, key))
                    yield from fallback_paths(nested, (*path, key))
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    yield from fallback_paths(nested, (*path, str(index)))

        self.assertEqual(list(fallback_paths(patched)), [])

    def test_no_route_uses_retired_anyrouter_sol(self):
        patched = install_runtime.patch_hermes_config(
            {
                "custom_providers": [
                    {"name": "anyrouter", "models": {"gpt-5.6-sol": {}}}
                ],
                "fallback_providers": [
                    {"provider": "anyrouter", "model": "gpt-5.6-sol"}
                ],
                "auxiliary": {
                    "approval": {
                        "provider": "anyrouter",
                        "model": "gpt-5.6-sol",
                        "fallback_chain": [
                            {"provider": "anyrouter", "model": "gpt-5.6-sol"}
                        ],
                    }
                },
            }
        )

        def routes(value):
            if isinstance(value, dict):
                yield value
                for nested in value.values():
                    yield from routes(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from routes(nested)

        self.assertFalse(
            any(
                route.get("provider") == "anyrouter"
                and route.get("model") == "gpt-5.6-sol"
                for route in routes(patched)
            )
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
        self.assertEqual(gpt["models"], {})

    def test_every_anyrouter_reference_pins_its_api_mode(self):
        """AnyRouter is never left to Hermes' chat_completions default.

        A model entry defaults to chat_completions unless it pins a mode, and
        anyrouter.top is not a host Hermes auto-detects. An unpinned reference
        is sent over the wrong wire and burns its retries on 404.
        """
        config = install_runtime.patch_hermes_config(
            {"custom_providers": [{"name": "anyrouter", "models": {}}]}
        )

        entry = install_runtime.provider(config, "anyrouter")
        self.assertEqual(entry.get("api_mode"), "codex_responses", entry)

    def test_patching_twice_is_idempotent(self):
        config = {
            "custom_providers": [
                {"name": "anyrouter", "api_key": "sk-test", "models": {}}
            ]
        }

        once = install_runtime.patch_hermes_config(copy.deepcopy(config))
        twice = install_runtime.patch_hermes_config(copy.deepcopy(once))

        self.assertEqual(once, twice)

    def test_skill_config_restores_native_background_defaults(self):
        patched = install_runtime.patch_skill_config(
            {
                "skills": {
                    "creation_nudge_interval": 0,
                    "external_dirs": [
                        str(install_runtime.PROJECT / "garden/skills"),
                        str(install_runtime.HOME / ".hermes/profiles/retired/skills"),
                    ],
                },
                "curator": {
                    "enabled": False,
                    "interval_hours": 24,
                    "consolidate": True,
                },
                "auxiliary": {
                    "background_review": {
                        "enabled": False,
                        "max_input_tokens": 1234,
                    }
                },
            }
        )

        self.assertNotIn("creation_nudge_interval", patched["skills"])
        self.assertEqual(patched["skills"]["external_dirs"], [])
        self.assertNotIn("enabled", patched["curator"])
        self.assertEqual(
            patched["curator"],
            {"interval_hours": 24, "consolidate": False},
        )
        self.assertNotIn("enabled", patched["auxiliary"]["background_review"])
        self.assertEqual(
            patched["auxiliary"]["background_review"]["max_input_tokens"],
            1234,
        )


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
        self.assertNotIn("memory", patched)

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
