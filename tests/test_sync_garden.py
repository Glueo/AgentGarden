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
    def test_sync_scope_excludes_runtime_owned_skills(self):
        self.assertEqual(sync_garden.SYNC_ROOTS, ("wiki", "sources"))

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

    def test_snapshot_commit_recovers_ambiguous_success_without_retry(self):
        class Snapshot:
            def __init__(self):
                self.commit_calls = 0
                self.log_calls = 0

            def commit(self, **kwargs):
                self.commit_calls += 1
                raise RuntimeError("HTTP 502: empty response")

            def log(self, **kwargs):
                self.log_calls += 1
                if self.log_calls == 1:
                    return []
                return [{"oid": "snapshot-id", "message": "operation-message"}]

        client = type("Client", (), {"snapshot": Snapshot()})()
        result = sync_garden.commit_snapshot_safely(client, message="operation-message")
        self.assertEqual(result["commit_oid"], "snapshot-id")
        self.assertTrue(result["recovered"])
        self.assertEqual(client.snapshot.commit_calls, 1)

    def test_snapshot_commit_leaves_ambiguous_operation_pending(self):
        class Snapshot:
            def __init__(self):
                self.commit_calls = 0

            def commit(self, **kwargs):
                self.commit_calls += 1
                raise RuntimeError("HTTP 502: empty response")

            def log(self, **kwargs):
                return []

        client = type("Client", (), {"snapshot": Snapshot()})()
        with self.assertRaisesRegex(RuntimeError, "left the operation pending"):
            sync_garden.commit_snapshot_safely(client, message="operation-message")
        self.assertEqual(client.snapshot.commit_calls, 1)

    def test_snapshot_commit_reuses_existing_operation(self):
        class Snapshot:
            def __init__(self):
                self.commit_calls = 0

            def commit(self, **kwargs):
                self.commit_calls += 1

            def log(self, **kwargs):
                return [{"oid": "existing-id", "message": "operation-message"}]

        client = type("Client", (), {"snapshot": Snapshot()})()
        result = sync_garden.commit_snapshot_safely(client, message="operation-message")
        self.assertEqual(result["commit_oid"], "existing-id")
        self.assertEqual(client.snapshot.commit_calls, 0)

    def test_snapshot_commit_does_not_retry_non_transient_errors(self):
        class Snapshot:
            def __init__(self):
                self.commit_calls = 0

            def commit(self, **kwargs):
                self.commit_calls += 1
                raise RuntimeError("HTTP 400: invalid request")

            def log(self, **kwargs):
                return []

        client = type("Client", (), {"snapshot": Snapshot()})()
        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            sync_garden.commit_snapshot_safely(client, message="operation-message")
        self.assertEqual(client.snapshot.commit_calls, 1)

    def test_snapshot_operation_is_reused_until_cleared(self):
        old = {"wiki/a.md": {"sha256": "before"}}
        new = {"wiki/a.md": {"sha256": "after"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending.json"
            first = sync_garden.load_or_create_snapshot_operation(old, new, path=path)
            second = sync_garden.load_or_create_snapshot_operation(old, new, path=path)
            self.assertEqual(first, second)
            sync_garden.clear_snapshot_operation(first, path=path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
