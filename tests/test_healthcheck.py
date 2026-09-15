from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/healthcheck.py"
SPEC = importlib.util.spec_from_file_location("healthcheck", MODULE_PATH)
healthcheck = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(healthcheck)


class SemanticHealthTests(unittest.TestCase):
    def test_unrecognized_task_payload_fails_closed(self):
        with self.assertRaises(ValueError):
            healthcheck.unwrap_tasks({"unexpected": []})

    def test_empty_nested_task_wrapper_fails_closed(self):
        with self.assertRaises(ValueError):
            healthcheck.unwrap_tasks({"result": {}})

    def test_unrecognized_listing_payload_fails_closed(self):
        with self.assertRaises(ValueError):
            healthcheck.list_items({"status": "ok", "unexpected": []})

    def test_listing_payload_with_non_mapping_item_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "non-object"):
            healthcheck.list_items({"result": [{"uri": "viking://ok"}, "bad"]})

    def test_task_payload_with_non_mapping_item_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "non-object"):
            healthcheck.unwrap_tasks({"result": [{"task_id": "ok"}, "bad"]})

    def test_task_limit_is_reported_as_truncated(self):
        tasks = [
            {"task_id": str(index), "task_type": "resource_add", "resource_id": str(index), "status": "completed", "updated_at": index}
            for index in range(200)
        ]
        report = healthcheck.summarize_tasks(tasks, limit=200)
        self.assertEqual(report["enumeration_errors"], ["task_limit_reached"])

    def test_latest_success_supersedes_historical_failure(self):
        tasks = [
            {"task_id": "old", "task_type": "session_commit", "resource_id": "session-a", "status": "failed", "updated_at": 1, "error": "old failure"},
            {"task_id": "new", "task_type": "session_commit", "resource_id": "session-a", "status": "completed", "updated_at": 2},
        ]
        report = healthcheck.summarize_tasks(tasks)
        self.assertEqual(report["historical_failures"], 1)
        self.assertEqual(report["unresolved_failed"], [])

    def test_completed_task_does_not_hide_a_distinct_nonterminal_task(self):
        tasks = [
            {"task_id": "still-running", "task_type": "resource_add", "resource_id": "resource-a", "status": "running", "updated_at": 1},
            {"task_id": "completed-later", "task_type": "resource_add", "resource_id": "resource-a", "status": "completed", "updated_at": 2},
        ]

        report = healthcheck.summarize_tasks(tasks)

        self.assertEqual(
            report["pending"],
            [{
                "task_id": "still-running",
                "task_type": "resource_add",
                "resource_id": "resource-a",
                "status": "running",
            }],
        )

    def test_latest_failed_and_pending_tasks_are_machine_readable(self):
        tasks = [
            {"task_id": "failed-id", "task_type": "session_commit", "resource_id": "session-a", "status": "failed", "updated_at": 3, "error": "HTTP 503 fixture"},
            {"task_id": "pending-id", "task_type": "resource_add", "resource_id": "viking://a", "status": "queued", "updated_at": 4},
        ]
        report = healthcheck.summarize_tasks(tasks)
        self.assertEqual(report["unresolved_failed"][0]["task_id"], "failed-id")
        self.assertEqual(report["pending"][0]["task_id"], "pending-id")
        self.assertNotIn("error", report["unresolved_failed"][0])

    def test_incomplete_task_records_cannot_hide_a_failure(self):
        tasks = [
            {"status": "failed", "updated_at": 1},
            {"status": "completed", "updated_at": 2},
        ]
        with self.assertRaises(ValueError):
            healthcheck.summarize_tasks(tasks)

    def test_malformed_task_timestamps_and_resource_ids_fail_closed(self):
        task = {"task_id": "a", "task_type": "session_commit", "status": "completed", "updated_at": 1}
        for extra in ({"updated_at": float("nan")}, {"updated_at": None}, {"updated_at": True}, {"resource_id": []}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                healthcheck.summarize_tasks([{**task, **extra}])

    def test_sync_manifest_pending_and_failed_are_reported(self):
        files = {
            "wiki/a.md": {"status": "pending", "task_id": "a"},
            "wiki/b.md": {"status": "failed", "task_id": "b", "failure": "safe reason"},
            "wiki/c.md": {"status": "completed"},
        }
        self.assertEqual(
            healthcheck.summarize_sync_manifest(files),
            {"pending": [{"path": "wiki/a.md", "task_id": "a"}], "failed": [{"path": "wiki/b.md", "task_id": "b", "reason": "safe reason"}]},
        )

    def test_statusless_and_unverified_manifest_entries_fail_closed(self):
        files = {
            "wiki/a.md": {"uri": "viking://a"},
            "wiki/b.md": {"status": "unverified", "uri": "viking://b"},
        }
        report = healthcheck.summarize_sync_manifest(files)
        self.assertEqual([item["path"] for item in report["failed"]], ["wiki/a.md", "wiki/b.md"])

    def test_completed_entries_with_cleanup_obligations_are_unhealthy(self):
        for field, value in (
            ("cleanup_uris", ["viking://source"]),
            ("cleanup_uri", "viking://source"),
            ("delete_pending", {"viking://source": {"relative": "wiki/source.md"}}),
        ):
            with self.subTest(field=field):
                report = healthcheck.summarize_sync_manifest(
                    {"wiki/a.md": {"status": "completed", field: value}}
                )
                self.assertEqual([item["path"] for item in report["pending"]], ["wiki/a.md"])

    def test_invalid_sync_manifest_fails_closed(self):
        with self.assertRaises(ValueError):
            healthcheck.validate_sync_manifest({"version": 2, "files": []})
        with self.assertRaises(ValueError):
            healthcheck.validate_sync_manifest({"version": 2, "files": {"wiki/a.md": "bad"}})

    def test_sync_manifest_reuses_the_synchronizers_scope_validation(self):
        payload = {"version": 2, "files": {"wiki/a.md": {
            "sha256": "a" * 64, "uri": "viking://outside/a.md", "text": True, "status": "completed",
        }}}
        with self.assertRaises(ValueError):
            healthcheck.validate_sync_manifest(payload)

    def test_legacy_manifest_is_normalized_without_mutating_the_input(self):
        payload = {"version": 1, "files": {"wiki/a.md": {
            "sha256": "a" * 64,
            "uri": "viking://user/gwen/resources/garden/wiki/a.md",
            "text": True,
        }}}
        files = healthcheck.validate_sync_manifest(payload)
        self.assertEqual(files["wiki/a.md"].get("status"), "unverified")
        self.assertNotIn("status", payload["files"]["wiki/a.md"])

    def test_completed_manifest_rejects_malformed_sha256(self):
        for digest in ("a" * 63, "a" * 65, "g" * 64, " " + "a" * 63, "a" * 64 + "\n"):
            with self.subTest(digest=digest), self.assertRaisesRegex(ValueError, "sha256|SHA-256"):
                healthcheck.validate_sync_manifest({"version": 2, "files": {"wiki/a.md": {
                    "sha256": digest, "uri": "viking://user/gwen/resources/garden/wiki/a.md",
                    "text": True, "status": "completed",
                }}})

    def test_session_enumeration_at_the_implicit_cap_fails_closed(self):
        sessions = [
            {"session_id": f"s{index}", "uri": f"viking://session/s{index}"}
            for index in range(1000)
        ]
        with patch.object(healthcheck, "http_json", return_value=(True, [])) as request:
            report = healthcheck.persistent_archive_health("http://127.0.0.1:1933", sessions)
        self.assertIn("session_limit_reached", report["enumeration_errors"])
        request.assert_not_called()

    def test_archive_listing_at_node_limit_is_reported_as_truncated(self):
        original = healthcheck.http_json
        healthcheck.http_json = lambda *args, **kwargs: (
            True,
            [{"name": f"entry-{index}", "uri": f"viking://session/a/history/{index}"} for index in range(1000)],
        )
        try:
            report = healthcheck.persistent_archive_health(
                "http://127.0.0.1:1933",
                [{"session_id": "a", "uri": "viking://session/a"}],
            )
        finally:
            healthcheck.http_json = original
        self.assertEqual(report["enumeration_errors"], ["a:node_limit_reached"])

    def test_malformed_session_records_are_reported_instead_of_skipped(self):
        records = [
            {"session_id": "s"},
            {"session_id": "s", "uri": None},
            {"session_id": "s", "uri": 42},
            {"session_id": "s", "uri": "   "},
            {"uri": "viking://session/s"},
        ]
        with patch.object(healthcheck, "http_json", return_value=(True, [])) as request:
            for record in records:
                with self.subTest(record=record):
                    report = healthcheck.persistent_archive_health(
                        "http://127.0.0.1:1933", {"result": [record]}
                    )
                    self.assertTrue(report["enumeration_errors"])
            request.assert_not_called()

    def test_malformed_session_wrapper_returns_a_structured_failure(self):
        report = healthcheck.persistent_archive_health(
            "http://127.0.0.1:1933", {"result": {"unexpected": []}}
        )
        self.assertTrue(report["enumeration_errors"])

    def test_malformed_archive_records_are_reported_instead_of_skipped(self):
        records = [
            {"name": ".failed.json"},
            {"uri": "viking://session/s/history/archive_1/.failed.json"},
            {"name": ".done", "uri": 42},
            {"name": "", "uri": "viking://session/s/history/archive_1/.done"},
            {"name": ".failed.json", "uri": "viking://session/s/history/archive_1/wrong"},
        ]
        for record in records:
            with self.subTest(record=record):
                with patch.object(healthcheck, "http_json", return_value=(True, {"result": [record]})):
                    report = healthcheck.persistent_archive_health(
                        "http://127.0.0.1:1933",
                        [{"session_id": "s", "uri": "viking://session/s"}],
                    )
                self.assertTrue(report["enumeration_errors"])

    def test_persistent_failed_archive_without_done_is_unresolved(self):
        entries = [
            {"name": ".failed.json", "uri": "viking://session/a/history/archive_1/.failed.json"},
            {"name": ".failed.json", "uri": "viking://session/a/history/archive_2/.failed.json"},
            {"name": ".done", "uri": "viking://session/a/history/archive_2/.done"},
        ]
        payloads = {
            "viking://session/a/history/archive_1/.failed.json": {"stage": "execution_memory", "blocked_by": ["vlm"]},
        }
        report = healthcheck.summarize_archive_markers(entries, payloads)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(report["unresolved_failed"], [{
            "archive_uri": "viking://session/a/history/archive_1",
            "stage": "execution_memory",
            "blocked_by": ["vlm"],
        }])


if __name__ == "__main__":
    unittest.main()
