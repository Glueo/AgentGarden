from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/install_runtime.py"
SPEC = importlib.util.spec_from_file_location("install_runtime", MODULE_PATH)
assert SPEC is not None
install_runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(install_runtime)


class AnyRouterResponseContractTests(unittest.TestCase):
    def test_anyrouter_preserves_required_include_during_reasoning_recovery(self):
        config = {
            "custom_providers": [
                {
                    "name": "anyrouter",
                    "models": {},
                    "extra_body": {
                        "include": [],
                        "metadata": {"diagnostic": "preserve"},
                    },
                },
                {"name": "unrelated", "extra_body": {"include": []}},
            ]
        }

        install_runtime.normalize_anyrouter_provider(
            config, selected_model=install_runtime.ANYROUTER_PRIMARY_MODEL,
        )

        anyrouter = install_runtime.provider(config, "anyrouter")
        self.assertEqual(
            anyrouter["extra_body"]["include"], ["reasoning.encrypted_content"],
        )
        self.assertEqual(
            anyrouter["extra_body"]["metadata"], {"diagnostic": "preserve"},
        )
        self.assertEqual(
            install_runtime.provider(config, "unrelated")["extra_body"], {"include": []},
        )


if __name__ == "__main__":
    unittest.main()
