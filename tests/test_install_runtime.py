from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


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

    def test_openviking_environment_update_preserves_desktop_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "CODERAPI_API_KEY=desktop-secret\n"
                "TERMINAL_CWD=/desktop/selected\n"
                "OPENVIKING_USER=old-user\n",
                encoding="utf-8",
            )

            install_runtime.update_openviking_environment(path)

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertIn("CODERAPI_API_KEY=desktop-secret", lines)
            self.assertIn("TERMINAL_CWD=/desktop/selected", lines)
            self.assertIn("OPENVIKING_USER=gwen", lines)

    def test_openviking_environment_update_removes_legacy_agent_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "OPENVIKING_AGENT=hermes\n"
                "OPENVIKING_USER=old-user\n",
                encoding="utf-8",
            )

            install_runtime.update_openviking_environment(path)

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertFalse(any(line.startswith("OPENVIKING_AGENT=") for line in lines))
            self.assertIn("OPENVIKING_USER=gwen", lines)

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

    def test_user_configured_memory_is_preserved(self):
        existing = {
            "memory": {"custom_templates_dir": "/user/templates", "other": True},
        }
        patched = install_runtime.patch_openviking_config(
            existing,
            vlm_key="ark-key",
            embedding_key="embedding-key",
        )
        self.assertEqual(
            patched["memory"],
            {"custom_templates_dir": "/user/templates", "other": True},
        )

    def test_user_configured_auth_mode_is_preserved(self):
        existing = {"server": {"auth_mode": "api_key", "root_api_key": "secret-root"}}
        patched = install_runtime.patch_openviking_config(
            existing,
            vlm_key="ark-key",
            embedding_key="embedding-key",
        )
        self.assertEqual(patched["server"]["auth_mode"], "api_key")
        self.assertEqual(patched["server"]["root_api_key"], "secret-root")

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
