from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import unquote


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/sync_garden.py"
SPEC = importlib.util.spec_from_file_location("sync_garden", MODULE_PATH)
sync_garden = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(sync_garden)


class IsolatedSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "wiki").mkdir()
        (root / "sources").mkdir()
        garden = patch.object(sync_garden, "GARDEN_ROOT", root)
        garden.start()
        self.addCleanup(garden.stop)


class SyncPlanTests(IsolatedSyncTests):
    def test_manifest_accepts_exact_sha256_without_changing_case(self):
        for value in ("0123456789abcdef" * 4, "0123456789ABCDEF" * 4, "0123456789aBcDeF" * 4):
            with self.subTest(value=value):
                entry = {"sha256": value, "uri": sync_garden.uri_for("wiki/a.md"),
                         "text": True, "status": "completed"}
                normalized = sync_garden.normalize_manifest({"version": 2, "files": {"wiki/a.md": entry}})
                self.assertEqual(normalized["files"]["wiki/a.md"]["sha256"], value)
                self.assertEqual(normalized["files"]["wiki/a.md"]["status"], "completed")

    def test_manifest_rejects_malformed_sha256_without_repairing(self):
        for value in (
            "", "a" * 63, "a" * 65, "g" * 64, "a" * 63 + "G",
            " " + "a" * 63, "a" * 63 + " ", " " + "a" * 64,
            "a" * 63 + "\n", "a" * 64 + "\n", "a" * 32 + "\t" + "a" * 31,
            "Ａ" * 64, "０" * 64, "a" * 63 + "é", None, 64, b"a" * 64,
        ):
            with self.subTest(value=value):
                entry = {"sha256": value, "uri": sync_garden.uri_for("wiki/a.md"),
                         "text": True, "status": "completed"}
                with self.assertRaisesRegex(ValueError, "sha256|SHA-256"):
                    sync_garden.normalize_manifest({"version": 2, "files": {"wiki/a.md": entry}})
                self.assertEqual(entry["sha256"], value)

    def test_legacy_manifest_entries_are_unverified(self):
        normalized = sync_garden.normalize_manifest(
            {"version": 1, "files": {"wiki/a.md": {"sha256": sync_garden.hash_bytes(b"fixture"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}}
        )
        self.assertEqual(normalized["files"]["wiki/a.md"]["status"], "unverified")
        current = {"wiki/a.md": {"sha256": sync_garden.hash_bytes(b"fixture"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}
        self.assertEqual(sync_garden.plan_changes(normalized["files"], current)["modify"], ["wiki/a.md"])

    def test_manifest_rejects_resource_uri_outside_its_expected_path(self):
        with self.assertRaisesRegex(ValueError, "expected path"):
            sync_garden.normalize_manifest(
                {
                    "version": 2,
                    "files": {
                        "wiki/a.md": {
                            "sha256": sync_garden.hash_bytes(b"fixture"),
                            "uri": sync_garden.BASE_URI,
                            "text": True,
                            "status": "completed",
                        }
                    },
                }
            )

    def test_manifest_rejects_cleanup_uri_outside_garden_root(self):
        with self.assertRaisesRegex(ValueError, "outside Garden root"):
            sync_garden.normalize_manifest(
                {
                    "version": 2,
                    "files": {
                        "wiki/a.md": {
                            "sha256": sync_garden.hash_bytes(b"fixture"),
                            "uri": sync_garden.uri_for("wiki/a.md"),
                            "text": True,
                            "status": "completed",
                            "cleanup_uris": ["viking://user/gwen/resources"],
                        }
                    },
                }
            )

    def test_exit_status_reflects_final_manifest_not_preflight_history(self):
        self.assertEqual(sync_garden.sync_exit_code({"wiki/a.md": {"status": "completed"}}), 0)
        self.assertEqual(sync_garden.sync_exit_code({"wiki/a.md": {"status": "failed"}}), 1)

    def test_sync_scope_excludes_runtime_owned_skills(self):
        self.assertEqual(sync_garden.SYNC_ROOTS, ("wiki", "sources"))

    def test_scan_rejects_symlink_even_when_it_points_to_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "sources").mkdir()
            outside = root / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            (root / "wiki/link.md").symlink_to(outside)
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                self.assertNotIn("wiki/link.md", sync_garden.scan())
            finally:
                sync_garden.GARDEN_ROOT = original

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
                new = {"wiki/a.md": {"sha256": "after", "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}
                sync_garden.apply_changes(client, {"add": [], "modify": ["wiki/a.md"], "move": [], "delete": []}, {}, new, wait=False)
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertEqual(client.calls[0][1]["to"], sync_garden.uri_for("wiki/a.md"))
        self.assertFalse(client.calls[0][1]["wait"])

    def test_waited_submission_without_task_id_completes_after_exact_tree_readback(self):
        class Client:
            def add_resource(self, path, **kwargs):
                return {"root_uri": kwargs["to"], "queue_status": {}}

            def ls(self, uri, **kwargs):
                return [{"uri": f"{uri}/a.md", "isDir": False}]

            def download_bytes(self, uri):
                if uri.endswith("/a.md"):
                    return b"hello"
                raise IsADirectoryError(uri)

            def wait_processed(self, **kwargs):
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/a.md").write_text("hello", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                entry = sync_garden.submission_entry(
                    Client(),
                    "wiki/a.md",
                    {"sha256": sync_garden.hash_bytes(b"hello"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True},
                    wait=True,
                )
            finally:
                sync_garden.GARDEN_ROOT = original

        self.assertEqual(entry["status"], "completed")
        self.assertNotIn("failure", entry)
        self.assertNotIn("task_id", entry)

    def test_tree_readback_accepts_openviking_sanitized_child_name(self):
        class Client:
            def ls(self, uri, **kwargs):
                return [{"uri": f"{uri}/2026-2027_Agent实习准备计划.md", "isDir": False}]

            def download_bytes(self, uri):
                if unquote(uri).endswith("/2026-2027_Agent实习准备计划.md"):
                    return b"content"
                raise IsADirectoryError(uri)

        actual = sync_garden.remote_resource_bytes(
            Client(),
            sync_garden.uri_for("wiki/plan.md"),
            "2026-2027 Agent实习准备计划.md",
        )
        self.assertEqual(actual, b"content")

    def test_waited_submission_without_task_id_fails_if_exact_tree_readback_differs(self):
        class Client:
            def add_resource(self, path, **kwargs):
                return {"root_uri": kwargs["to"], "queue_status": {}}

            def ls(self, uri, **kwargs):
                return [{"uri": f"{uri}/a.md", "isDir": False}]

            def download_bytes(self, uri):
                if uri.endswith("/a.md"):
                    return b"stale"
                raise IsADirectoryError(uri)

            def wait_processed(self, **kwargs):
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/a.md").write_text("hello", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                entry = sync_garden.submission_entry(
                    Client(),
                    "wiki/a.md",
                    {"sha256": sync_garden.hash_bytes(b"hello"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True},
                    wait=True,
                )
            finally:
                sync_garden.GARDEN_ROOT = original

        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["failure"], "waited add completed but remote content differs")
        self.assertNotIn("task_id", entry)
        self.assertTrue(sync_garden.original_upload_finished(Client(), entry))

    def test_markdown_verification_compares_openviking_canonical_body(self):
        local = b"---\nid: a\ntopics: [x]\n---\n\n# Title\n\nBody\n"
        remote = b"\n# Title\n\nBody\n"
        self.assertTrue(sync_garden.remote_content_matches(local, remote, text=True))

    def test_markdown_verification_rejects_different_body(self):
        local = b"---\nid: a\n---\n\n# Title\n\nBody\n"
        remote = b"\n# Title\n\nStale\n"
        self.assertFalse(sync_garden.remote_content_matches(local, remote, text=True))

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


class AsyncLifecycleTests(IsolatedSyncTests):
    class Client:
        def __init__(self):
            self.tasks = {"task-1": "queued"}
            self.objects = {}
            self.removed = []

        def get_task(self, task_id):
            return {"task_id": task_id, "status": self.tasks[task_id]}

        def download_bytes(self, uri):
            return self.objects.get(uri)

        def delete(self, uri):
            self.removed.append(uri)
            self.objects.pop(uri, None)

    def test_async_acceptance_remains_pending_until_task_and_content_succeed(self):
        client = self.Client()
        files = {"wiki/a.md": {"sha256": sync_garden.hash_bytes(b"hello"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True, "status": "pending", "task_id": "task-1"}}
        local = {"wiki/a.md": {"sha256": sync_garden.hash_bytes(b"hello"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True, "bytes": b"hello"}}
        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: local[path]["bytes"])
        self.assertEqual(files["wiki/a.md"]["status"], "pending")
        client.tasks["task-1"] = "completed"
        client.objects[sync_garden.uri_for("wiki/a.md")] = b"hello"
        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: local[path]["bytes"])
        self.assertEqual(files["wiki/a.md"]["status"], "completed")
        self.assertEqual(report["completed"], ["wiki/a.md"])

    def test_terminal_success_with_mismatched_content_fails_and_is_retryable(self):
        client = self.Client()
        client.tasks["task-1"] = "completed"
        client.objects[sync_garden.uri_for("wiki/a.md")] = b"stale"
        files = {
            "wiki/a.md": {
                "sha256": sync_garden.hash_bytes(b"hello"),
                "uri": sync_garden.uri_for("wiki/a.md"),
                "text": True,
                "status": "pending",
                "task_id": "task-1",
            }
        }

        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"hello")

        self.assertEqual(report["failed"], ["wiki/a.md"])
        self.assertEqual(files["wiki/a.md"]["status"], "failed")
        self.assertEqual(sync_garden.sync_exit_code(files), 1)
        current = {
            "wiki/a.md": {
                "sha256": sync_garden.hash_bytes(b"hello"),
                "uri": sync_garden.uri_for("wiki/a.md"),
                "text": True,
            }
        }
        self.assertEqual(sync_garden.plan_changes(files, current)["modify"], ["wiki/a.md"])

    def test_failed_async_task_stays_retryable(self):
        client = self.Client()
        client.tasks["task-1"] = "failed"
        files = {"wiki/a.md": {"sha256": "digest", "uri": sync_garden.uri_for("wiki/a.md"), "text": True, "status": "pending", "task_id": "task-1"}}
        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"hello")
        self.assertEqual(files["wiki/a.md"]["status"], "failed")
        self.assertEqual(report["failed"], ["wiki/a.md"])
        current = {"wiki/a.md": {"sha256": "digest", "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}
        self.assertEqual(sync_garden.plan_changes(files, current)["modify"], ["wiki/a.md"])

    def test_missing_async_task_becomes_retryable_failure(self):
        class MissingTaskClient:
            def get_task(self, task_id):
                return None

        client = MissingTaskClient()
        files = {
            "wiki/a.md": {
                "sha256": "digest",
                "uri": sync_garden.uri_for("wiki/a.md"),
                "text": True,
                "status": "pending",
                "task_id": "expired-task",
            }
        }

        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"hello")

        self.assertEqual(report["failed"], ["wiki/a.md"])
        self.assertEqual(files["wiki/a.md"]["status"], "failed")
        self.assertIn("not found", files["wiki/a.md"]["failure"])
        current = {"wiki/a.md": {"sha256": "digest", "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}
        self.assertEqual(sync_garden.plan_changes(files, current)["modify"], ["wiki/a.md"])

    def test_existing_failed_entry_is_reported(self):
        client = self.Client()
        files = {"wiki/a.md": {"sha256": "digest", "uri": sync_garden.uri_for("wiki/a.md"), "text": True, "status": "failed"}}
        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"hello")
        self.assertEqual(report["failed"], ["wiki/a.md"])

    def test_local_edit_waits_for_prior_task_before_resubmission(self):
        client = self.Client()
        files = {"wiki/a.md": {"sha256": sync_garden.hash_bytes(b"old"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True, "status": "pending", "task_id": "task-1"}}
        current = {"wiki/a.md": {"sha256": sync_garden.hash_bytes(b"new"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}

        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"new")
        self.assertEqual(report["pending"], ["wiki/a.md"])
        self.assertEqual(sync_garden.plan_changes(files, current)["modify"], [])

        client.tasks["task-1"] = "completed"
        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"new")
        self.assertEqual(report["failed"], ["wiki/a.md"])
        self.assertEqual(sync_garden.plan_changes(files, current)["modify"], ["wiki/a.md"])

    def test_modified_pending_move_keeps_cleanup_uri(self):
        class Client:
            def add_resource(self, path, **kwargs):
                return {"task_id": "replacement"}

        old = {"wiki/new.md": {"sha256": "old", "uri": sync_garden.uri_for("wiki/new.md"), "text": True, "status": "failed", "cleanup_uris": [sync_garden.uri_for("wiki/old.md")]}}
        new = {"wiki/new.md": {"sha256": "new", "uri": sync_garden.uri_for("wiki/new.md"), "text": True}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/new.md").write_text("new", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                files = sync_garden.apply_changes(
                    Client(),
                    {"add": [], "modify": ["wiki/new.md"], "move": [], "delete": []},
                    old,
                    new,
                    wait=False,
                )
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertEqual(files["wiki/new.md"]["cleanup_uris"], [sync_garden.uri_for("wiki/old.md")])

    def test_completed_move_cleans_only_manifest_owned_source(self):
        client = self.Client()
        client.tasks["task-1"] = "completed"
        old_uri = sync_garden.uri_for("wiki/old.md")
        new_uri = sync_garden.uri_for("wiki/new.md")
        client.objects = {old_uri: b"hello", new_uri: b"hello"}
        files = {"wiki/new.md": {"sha256": sync_garden.hash_bytes(b"hello"), "uri": new_uri, "text": True, "status": "pending", "task_id": "task-1", "cleanup_uris": [old_uri], "cleanup_sources": {old_uri: "wiki/old.md"}}}
        sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"hello", deleter=client)
        self.assertEqual(client.removed, [old_uri])
        self.assertNotIn("cleanup_uris", files["wiki/new.md"])

    def test_completed_move_with_mismatched_content_fails_before_cleanup(self):
        client = self.Client()
        client.objects = {sync_garden.uri_for("wiki/old.md"): b"hello", sync_garden.uri_for("wiki/new.md"): b"stale"}
        files = {
            "wiki/new.md": {
                "sha256": sync_garden.hash_bytes(b"hello"),
                "uri": sync_garden.uri_for("wiki/new.md"),
                "text": True,
                "status": "completed",
                "cleanup_uris": [sync_garden.uri_for("wiki/old.md")],
            }
        }

        report = sync_garden.reconcile_pending(client, files, local_bytes=lambda path: b"hello")

        self.assertEqual(report["failed"], ["wiki/new.md"])
        self.assertEqual(files["wiki/new.md"]["status"], "failed")
        self.assertEqual(client.removed, [])

    def test_first_move_checkpoint_replaces_source_atomically(self):
        class Client:
            def add_resource(self, path, **kwargs):
                return {"task_id": "move-task"}

        old = {"wiki/old.md": {"sha256": "same", "uri": sync_garden.uri_for("wiki/old.md"), "text": True, "status": "completed"}}
        new = {"wiki/new.md": {"sha256": "same", "uri": sync_garden.uri_for("wiki/new.md"), "text": True}}
        checkpoints = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/new.md").write_text("new", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                sync_garden.apply_changes(
                    Client(),
                    {"add": [], "modify": [], "move": [("wiki/old.md", "wiki/new.md")], "delete": []},
                    old,
                    new,
                    wait=False,
                    checkpoint=lambda files: checkpoints.append({key: dict(value) for key, value in files.items()}),
                )
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertNotIn("wiki/old.md", checkpoints[0])
        self.assertEqual(checkpoints[0]["wiki/new.md"]["cleanup_uris"], [sync_garden.uri_for("wiki/old.md")])

    def test_deleted_pending_move_waits_for_task_before_reverse_move(self):
        client = self.Client()
        files = {"wiki/new.md": {"sha256": "same", "uri": sync_garden.uri_for("wiki/new.md"), "text": True, "status": "pending", "task_id": "task-1", "cleanup_uri": sync_garden.uri_for("wiki/old.md")}}
        report = sync_garden.reconcile_pending(
            client,
            files,
            local_bytes=lambda path: (_ for _ in ()).throw(FileNotFoundError(path)),
        )
        self.assertEqual(report["pending"], ["wiki/new.md"])
        current = {"wiki/old.md": {"sha256": "same", "uri": sync_garden.uri_for("wiki/old.md"), "text": True}}
        self.assertEqual(sync_garden.plan_changes(files, current), {"add": ["wiki/old.md"], "modify": [], "move": [], "delete": []})

    def test_deleted_pending_move_becomes_retryable_after_terminal_success(self):
        client = self.Client()
        client.tasks["task-1"] = "completed"
        client.objects[sync_garden.uri_for("wiki/new.md")] = b"same"
        files = {
            "wiki/new.md": {
                "sha256": sync_garden.hash_bytes(b"same"),
                "uri": sync_garden.uri_for("wiki/new.md"),
                "text": True,
                "status": "pending",
                "task_id": "task-1",
                "cleanup_uri": sync_garden.uri_for("wiki/old.md"),
            }
        }

        report = sync_garden.reconcile_pending(
            client,
            files,
            local_bytes=lambda path: (_ for _ in ()).throw(FileNotFoundError(path)),
        )

        self.assertEqual(report["failed"], ["wiki/new.md"])
        current = {"wiki/old.md": {"sha256": sync_garden.hash_bytes(b"same"), "uri": sync_garden.uri_for("wiki/old.md"), "text": True}}
        self.assertTrue(files["wiki/new.md"]["delete_pending"])
        self.assertEqual(sync_garden.plan_changes(files, current), {
            "add": ["wiki/old.md"], "modify": [], "move": [], "delete": ["wiki/new.md"],
        })

    def test_chained_move_preserves_all_cleanup_uris(self):
        class Client:
            def add_resource(self, path, **kwargs):
                return {"task_id": "next-move"}

        old = {
            "wiki/b.md": {
                "sha256": "same",
                "uri": sync_garden.uri_for("wiki/b.md"),
                "text": True,
                "status": "failed",
                "cleanup_uris": [sync_garden.uri_for("wiki/a.md")],
            }
        }
        new = {"wiki/c.md": {"sha256": "same", "uri": sync_garden.uri_for("wiki/c.md"), "text": True}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/c.md").write_text("same", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                files = sync_garden.apply_changes(
                    Client(),
                    {"add": [], "modify": [], "move": [("wiki/b.md", "wiki/c.md")], "delete": []},
                    old,
                    new,
                    wait=False,
                )
            finally:
                sync_garden.GARDEN_ROOT = original

        self.assertEqual(files["wiki/c.md"]["cleanup_uris"], [sync_garden.uri_for("wiki/a.md"), sync_garden.uri_for("wiki/b.md")])

    def test_wait_error_count_is_failure(self):
        status = {"Embedding": {"processed": 1, "error_count": 1, "errors": [{"message": "safe fixture"}]}}
        with self.assertRaisesRegex(RuntimeError, "processing errors"):
            sync_garden.require_clean_queue(status)

    def test_each_accepted_submission_is_checkpointed_before_later_failure(self):
        class Client:
            def __init__(self):
                self.calls = 0

            def add_resource(self, path, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise ConnectionError("second failed")
                return {"task_id": "first-task"}

        checkpoints = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            for name in ("a.md", "b.md"):
                (root / "wiki" / name).write_text(name, encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                new = {
                    name: {"sha256": name, "uri": sync_garden.uri_for(name), "text": True}
                    for name in ("wiki/a.md", "wiki/b.md")
                }
                with self.assertRaises(ConnectionError):
                    sync_garden.apply_changes(
                        Client(),
                        {"add": list(new), "modify": [], "move": [], "delete": []},
                        {},
                        new,
                        wait=False,
                        checkpoint=lambda files: checkpoints.append({key: dict(value) for key, value in files.items()}),
                    )
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertEqual(checkpoints[-1]["wiki/a.md"]["task_id"], "first-task")

    def test_wait_failure_after_acceptance_keeps_task_checkpoint(self):
        class Client:
            def add_resource(self, path, **kwargs):
                return {"task_id": "accepted-task"}

            def wait_processed(self, **kwargs):
                raise TimeoutError("wait failed")

        checkpoints = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/a.md").write_text("a", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                new = {"wiki/a.md": {"sha256": "a", "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}
                with self.assertRaises(TimeoutError):
                    sync_garden.apply_changes(
                        Client(),
                        {"add": ["wiki/a.md"], "modify": [], "move": [], "delete": []},
                        {}, new, wait=True,
                        checkpoint=lambda files: checkpoints.append({key: dict(value) for key, value in files.items()}),
                    )
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertEqual(checkpoints[-1]["wiki/a.md"]["task_id"], "accepted-task")

    def test_delete_is_waited_before_manifest_entry_is_removed(self):
        import json
        from email.message import Message
        from urllib.error import HTTPError
        from urllib.parse import parse_qs, urlsplit

        client = self.Client()
        uri = sync_garden.uri_for("wiki/a.md")
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"status": "ok", "result": {
            "uri": uri, "semantic_root_uri": uri.rsplit("/", 1)[0],
            "semantic_status": "complete", "queue_status": {},
        }}).encode()
        adapter = sync_garden.GardenDeletionHTTP("http://fixture.invalid")
        old = {"wiki/a.md": {"sha256": "a", "uri": sync_garden.uri_for("wiki/a.md"), "status": "completed"}}
        with patch.object(adapter.opener, "open", side_effect=[
            response, HTTPError("http://fixture.invalid", 404, "not found", Message(), None),
        ]) as request:
            result = sync_garden.apply_changes(
                client,
                {"add": [], "modify": [], "move": [], "delete": ["wiki/a.md"]},
                old, {}, wait=False, deleter=adapter,
            )
        self.assertEqual(result, {})
        self.assertEqual(parse_qs(urlsplit(request.call_args_list[0].args[0].full_url).query)["wait"], ["true"])


if __name__ == "__main__":
    unittest.main()
