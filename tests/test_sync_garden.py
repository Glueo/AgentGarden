from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/sync_garden.py"
SPEC = importlib.util.spec_from_file_location("sync_garden", MODULE_PATH)
sync_garden = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(sync_garden)


class SyncPlanTests(unittest.TestCase):
    def test_stable_uri_escapes_each_path_segment(self):
        self.assertEqual(
            sync_garden.uri_for("wiki/中文 note.md"),
            "viking://user/gwen/resources/garden/wiki/%E4%B8%AD%E6%96%87%20note.md",
        )

    def test_identical_hash_becomes_move(self):
        old = {"wiki/old.md": {"sha256": "same", "uri": "old", "text": True}}
        new = {"wiki/new.md": {"sha256": "same", "uri": "new", "text": True}}
        plan = sync_garden.plan_changes(old, new)
        self.assertEqual(plan["move"], [("wiki/old.md", "wiki/new.md")])
        self.assertFalse(plan["add"])
        self.assertFalse(plan["delete"])

    def test_modified_is_not_duplicated(self):
        old = {"wiki/a.md": {"sha256": "before", "uri": "same", "text": True}}
        new = {"wiki/a.md": {"sha256": "after", "uri": "same", "text": True}}
        self.assertEqual(sync_garden.plan_changes(old, new)["modify"], ["wiki/a.md"])

    def test_modified_resource_uses_incremental_add_to_same_uri(self):
        class Client:
            def __init__(self):
                self.calls = []

            def add_resource(self, path, **kwargs):
                self.calls.append((path, kwargs))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/a.md").write_text("updated", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                client = Client()
                new = {"wiki/a.md": {"sha256": "after", "uri": "viking://stable/a", "text": True}}
                sync_garden.apply_changes(client, {"add": [], "modify": ["wiki/a.md"], "move": [], "delete": []}, {}, new, wait=False)
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertEqual(client.calls[0][1]["to"], "viking://stable/a")
        self.assertFalse(client.calls[0][1]["wait"])


if __name__ == "__main__":
    unittest.main()
