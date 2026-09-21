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
        (root / "resources").mkdir()
        garden = patch.object(sync_garden, "GARDEN_ROOT", root)
        garden.start()
        self.addCleanup(garden.stop)


class SyncPlanTests(IsolatedSyncTests):
    def test_scan_ignores_resources_directory_entirely(self):
        for relative in ("resources/site/index.html", "resources/site/robots.txt",
                         "resources/site/sitemap.xml", "wiki/a.md"):
            path = sync_garden.GARDEN_ROOT / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        self.assertEqual(set(sync_garden.scan()), {"wiki/a.md"})
        self.assertTrue(all((sync_garden.GARDEN_ROOT / p).is_file() for p in
                            ("resources/site/index.html", "resources/site/robots.txt",
                             "resources/site/sitemap.xml")))

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

    def test_sync_scope_is_wiki_only(self):
        self.assertEqual(sync_garden.SYNC_ROOTS, ("wiki",))

    def test_scan_includes_wiki_and_ignores_resources_and_legacy_sources(self):
        (sync_garden.GARDEN_ROOT / "wiki/page.html").write_bytes(b"<!doctype html><title>source</title>")
        (sync_garden.GARDEN_ROOT / "resources/page.html").write_bytes(b"<!doctype html><title>archive</title>")
        (sync_garden.GARDEN_ROOT / "sources").mkdir()
        (sync_garden.GARDEN_ROOT / "sources/derived.md").write_text("processed", encoding="utf-8")

        scanned = sync_garden.scan()

        self.assertIn("wiki/page.html", scanned)
        self.assertNotIn("resources/page.html", scanned)
        self.assertNotIn("sources/derived.md", scanned)

    def test_scan_rejects_symlink_even_when_it_points_to_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "resources").mkdir()
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

    def test_modified_resource_writes_verbatim_to_same_uri(self):
        class Client:
            def __init__(self):
                self.calls = []

            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                self.calls.append((uri, content, mode, wait))

            def download_bytes(self, uri):
                return b"updated"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/a.md").write_text("updated", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                client = Client()
                new = {"wiki/a.md": {"sha256": sync_garden.hash_bytes(b"updated"), "uri": sync_garden.uri_for("wiki/a.md"), "text": True}}
                sync_garden.apply_changes(client, {"add": [], "modify": ["wiki/a.md"], "move": [], "delete": []}, {}, new, wait=False)
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertEqual(client.calls[0][0], sync_garden.uri_for("wiki/a.md"))
        self.assertEqual(client.calls[0][1], "updated")
        self.assertFalse(client.calls[0][3])

    def test_waited_markdown_write_completes_without_task_id(self):
        class Client:
            def __init__(self):
                self.written = ""

            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                self.written = content
                return {"queue_status": {}}

            def download_bytes(self, uri):
                return self.written.encode("utf-8")

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

    def test_waited_markdown_write_fails_if_readback_differs(self):
        class Client:
            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                return {"queue_status": {}}

            def download_bytes(self, uri):
                return b"stale"

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
        self.assertEqual(entry["failure"], "uploaded text content differs on readback")
        self.assertNotIn("task_id", entry)

    def test_markdown_verification_compares_openviking_canonical_body(self):
        local = b"---\nid: a\ntopics: [x]\n---\n\n# Title\n\nBody\n"
        remote = b"\n# Title\n\nBody\n"
        self.assertTrue(sync_garden.remote_content_matches(local, remote, text=True))

    def test_markdown_verification_rejects_different_body(self):
        local = b"---\nid: a\n---\n\n# Title\n\nBody\n"
        remote = b"\n# Title\n\nStale\n"
        self.assertFalse(sync_garden.remote_content_matches(local, remote, text=True))

    def test_markdown_verification_tolerates_trailing_newline_normalization(self):
        local = b"# Title\n\nBody\n"
        remote = b"# Title\n\nBody"
        self.assertTrue(sync_garden.remote_content_matches(local, remote, text=True))
        self.assertTrue(sync_garden.remote_content_matches(remote, local, text=True))

    def test_parsed_html_stat_without_readable_child_is_not_verification(self):
        class ParsedClient:
            def __init__(self):
                self.stat_calls = 0

            def download_bytes(self, uri):
                return None

            def ls(self, uri, **kwargs):
                raise FileNotFoundError(uri)

            def stat(self, uri):
                self.stat_calls += 1
                return {"uri": uri, "name": "page.html", "isDir": True}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/page.html").write_bytes(b"<!doctype html><title>x</title>")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                entry = {
                    "sha256": sync_garden.hash_bytes(b"<!doctype html><title>x</title>"),
                    "uri": sync_garden.uri_for("wiki/page.html"),
                    "text": True,
                }
                client = ParsedClient()
                ok = sync_garden.verified_content(
                    client, "wiki/page.html", entry,
                    lambda rel: (root / rel).read_bytes(),
                )
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertFalse(ok)
        self.assertEqual(client.stat_calls, 1)

    def test_parsed_html_child_markdown_verifies_resource_tree_ingestion(self):
        local = (
            b"<!doctype html><html><head><title>Fresh page</title></head>"
            b"<body><nav>Discarded navigation</nav><main><h1>Fresh page</h1>"
            b"<p>Fresh body with enough substantive content for extraction.</p>"
            b"</main></body></html>"
        )
        from openviking.parse.parsers.html import HTMLParser as OpenVikingHTMLParser
        parsed_child = OpenVikingHTMLParser()._html_to_markdown(
            local.decode("utf-8"), base_url=""
        ).encode("utf-8")

        class ParsedClient:
            def download_bytes(self, uri):
                if uri.endswith("/page.md"):
                    return parsed_child
                raise IsADirectoryError(uri)

            def ls(self, uri, **kwargs):
                return [{
                    "name": "page.md",
                    "isDir": False,
                    "uri": uri + "/page.md",
                }]

            def stat(self, uri):
                return {"uri": uri, "name": "page.html", "isDir": True}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/page.html").write_bytes(local)
            entry = {
                "sha256": sync_garden.hash_bytes(local),
                "uri": sync_garden.uri_for("wiki/page.html"),
                "text": True,
            }
            self.assertTrue(sync_garden.verified_content(
                ParsedClient(), "wiki/page.html", entry,
                lambda rel: (root / rel).read_bytes(),
            ))

    def test_parsed_html_stale_child_does_not_verify_current_source(self):
        class ParsedClient:
            def __init__(self, child):
                self.child = child

            def download_bytes(self, uri):
                if uri.endswith("/page.md"):
                    return self.child
                raise IsADirectoryError(uri)

            def ls(self, uri, **kwargs):
                return [{"name": "page.md", "isDir": False, "uri": uri + "/page.md"}]

            def stat(self, uri):
                return {"uri": uri, "name": "page.html", "isDir": True}

        local = b"<!doctype html><title>Fresh page</title><body><p>Fresh body changed substantially</p></body>"
        entry = {
            "sha256": sync_garden.hash_bytes(local),
            "uri": sync_garden.uri_for("wiki/page.html"),
            "text": True,
        }
        for stale in (b"# Old page\n\nOld body\n", b"# Fresh page\n", b"# Fresh page\n\nOld body\n"):
            with self.subTest(stale=stale):
                self.assertFalse(sync_garden.verified_content(
                    ParsedClient(stale), "wiki/page.html", entry, lambda rel: local,
                ))

    def test_unreadable_regular_or_tree_resource_fails_closed(self):
        local = b"<!doctype html><title>Fresh page</title><body>Fresh body</body>"
        entry = {
            "sha256": sync_garden.hash_bytes(local),
            "uri": sync_garden.uri_for("wiki/page.html"),
            "text": True,
        }

        class UnreadableRegular:
            def download_bytes(self, uri):
                raise PermissionError("denied")

            def ls(self, uri, **kwargs):
                raise PermissionError("denied")

            def stat(self, uri):
                return {"uri": uri, "name": "page.html", "isDir": False}

        class UnreadableTree:
            def download_bytes(self, uri):
                if uri.endswith("/page.md"):
                    raise PermissionError("denied")
                raise IsADirectoryError(uri)

            def ls(self, uri, **kwargs):
                return [{"name": "page.md", "isDir": False, "uri": uri + "/page.md"}]

            def stat(self, uri):
                return {"uri": uri, "name": "page.html", "isDir": True}

        for client in (UnreadableRegular(), UnreadableTree()):
            with self.subTest(client=type(client).__name__):
                self.assertFalse(sync_garden.verified_content(
                    client, "wiki/page.html", entry, lambda rel: local,
                ))

    def test_semantic_tree_fallback_is_restricted_to_html(self):
        local = b"Fresh page Fresh body"
        uri = sync_garden.uri_for("wiki/page.txt")

        class ParsedClient:
            def download_bytes(self, target):
                if target.endswith("/page.md"):
                    return b"# Fresh page\n\nFresh body\n"
                raise IsADirectoryError(target)

            def ls(self, target, **kwargs):
                return [{"name": "page.md", "isDir": False, "uri": target + "/page.md"}]

            def stat(self, target):
                return {"uri": target, "name": "page.txt", "isDir": True}

        self.assertFalse(sync_garden.verified_content(
            ParsedClient(), "wiki/page.txt",
            {"sha256": sync_garden.hash_bytes(local), "uri": uri, "text": True},
            lambda rel: local,
        ))

    def test_parsed_markdown_tree_still_requires_matching_child_bytes(self):
        local = b"# Fresh page\n\nFresh body\n"
        uri = sync_garden.uri_for("wiki/page.md")

        class ParsedClient:
            def __init__(self, child):
                self.child = child

            def download_bytes(self, target):
                if target.endswith("/parsed.md"):
                    return self.child
                raise IsADirectoryError(target)

            def ls(self, target, **kwargs):
                return [{"name": "parsed.md", "isDir": False, "uri": target + "/parsed.md"}]

        entry = {"sha256": sync_garden.hash_bytes(local), "uri": uri, "text": True}
        self.assertTrue(sync_garden.verified_content(
            ParsedClient(local), "wiki/page.md", entry, lambda rel: local,
        ))
        self.assertFalse(sync_garden.verified_content(
            ParsedClient(b"# Stale page\n"), "wiki/page.md", entry, lambda rel: local,
        ))

    def test_direct_binary_readback_requires_exact_bytes(self):
        local = b"binary\x00payload\n"
        uri = sync_garden.uri_for("wiki/blob.bin")

        class Client:
            def __init__(self, remote):
                self.remote = remote

            def download_bytes(self, target):
                return self.remote

        entry = {"sha256": sync_garden.hash_bytes(local), "uri": uri, "text": False}
        self.assertTrue(sync_garden.verified_content(Client(local), "wiki/blob.bin", entry, lambda rel: local))
        self.assertFalse(sync_garden.verified_content(
            Client(local.rstrip()), "wiki/blob.bin", entry, lambda rel: local,
        ))

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
            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                return {}

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
            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                return {}

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
            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                return {}

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

            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise ConnectionError("second failed")
                return {}

            def download_bytes(self, uri):
                return uri.rsplit("/", 1)[-1].encode("utf-8")

        checkpoints = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            new = {}
            for name in ("a.md", "b.md"):
                (root / "wiki" / name).write_text(name, encoding="utf-8")
                relative = "wiki/" + name
                new[relative] = {"sha256": sync_garden.hash_bytes(name.encode("utf-8")),
                                 "uri": sync_garden.uri_for(relative), "text": True}
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
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
        self.assertEqual(checkpoints[-1]["wiki/a.md"]["status"], "completed")

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
            (root / "wiki/a.txt").write_text("a", encoding="utf-8")
            original = sync_garden.GARDEN_ROOT
            sync_garden.GARDEN_ROOT = root
            try:
                new = {"wiki/a.txt": {"sha256": "a", "uri": sync_garden.uri_for("wiki/a.txt"), "text": True}}
                with self.assertRaises(TimeoutError):
                    sync_garden.apply_changes(
                        Client(),
                        {"add": ["wiki/a.txt"], "modify": [], "move": [], "delete": []},
                        {}, new, wait=True,
                        checkpoint=lambda files: checkpoints.append({key: dict(value) for key, value in files.items()}),
                    )
            finally:
                sync_garden.GARDEN_ROOT = original
        self.assertEqual(checkpoints[-1]["wiki/a.txt"]["task_id"], "accepted-task")

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
