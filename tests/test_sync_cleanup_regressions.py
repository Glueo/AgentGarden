from __future__ import annotations

import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/sync_garden.py"
SPEC = importlib.util.spec_from_file_location("sync_cleanup_regressions", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
sync_garden = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_garden)


def metadata(relative: str, content: bytes = b"same", **extra) -> dict:
    return {
        "sha256": sync_garden.hash_bytes(content),
        "uri": sync_garden.uri_for(relative),
        "text": True,
        **extra,
    }


class ResourceClient:
    def __init__(self, objects: dict[str, bytes], *, deletion_status: str = "complete"):
        self.objects = dict(objects)
        self.removed = []
        self.deletion_status = deletion_status
        self.semantic_by_uri = {}
        self.task_state = "completed"

    def get_task(self, task_id):
        return {"task_id": task_id, "status": self.task_state}

    def download_bytes(self, uri):
        return self.objects.get(uri)

    def stat(self, uri):
        return {"isDir": False}

    def write(self, uri, content, mode="replace", wait=False, **kwargs):
        self.objects[uri] = content.encode("utf-8") if isinstance(content, str) else content
        return {}

    def rm(self, uri, **kwargs):
        raise AssertionError("The SDK rm method discards semantic results and must not be used")

    def delete(self, uri):
        adapter = sync_garden.GardenDeletionHTTP("http://fixture.invalid")

        def response(request, **kwargs):
            target = parse_qs(urlsplit(request.full_url).query)["uri"][0]
            if request.get_method() == "DELETE":
                present = any(item == target or item.startswith(target + "/") for item in self.objects)
                self.removed.append(target)
                if not present:
                    raise not_found()
                for item in list(self.objects):
                    if item == target or item.startswith(target + "/"):
                        del self.objects[item]
                status = self.semantic_by_uri.get(target, self.deletion_status)
                return HTTPResponse(deletion_payload(target, semantic_status=status))
            if target not in self.objects:
                raise not_found()
            return HTTPResponse({"status": "ok", "result": []})

        with patch.object(adapter.opener, "open", side_effect=response):
            return adapter.delete(uri)


class IsolatedGardenTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "wiki").mkdir()
        (self.root / "resources").mkdir()
        garden = patch.object(sync_garden, "GARDEN_ROOT", self.root)
        garden.start()
        self.addCleanup(garden.stop)


class CleanupRegressionTests(IsolatedGardenTests):
    def test_cleanup_cannot_authorize_a_whole_sync_branch(self):
        files = {
            "wiki/b.md": metadata(
                "wiki/b.md", status="completed", cleanup_uris=[sync_garden.BASE_URI + "/wiki"]
            )
        }
        with self.assertRaises(ValueError):
            sync_garden.normalize_manifest({"version": 2, "files": files})

    def test_completed_move_preserves_recreated_source(self):
        a_uri = sync_garden.uri_for("wiki/a.md")
        b_uri = sync_garden.uri_for("wiki/b.md")
        files = {
            "wiki/a.md": metadata("wiki/a.md", b"recreated", status="completed"),
            "wiki/b.md": metadata(
                "wiki/b.md", status="pending", task_id="move-task", cleanup_uris=[a_uri],
                cleanup_sources={a_uri: "wiki/a.md"}
            ),
        }
        current = {
            "wiki/a.md": metadata("wiki/a.md", b"recreated"),
            "wiki/b.md": metadata("wiki/b.md"),
        }
        local = {"wiki/a.md": b"recreated", "wiki/b.md": b"same"}
        client = ResourceClient({a_uri: b"recreated", b_uri: b"same"})
        with patch.object(sync_garden, "scan", return_value=current):
            sync_garden.reconcile_pending(client, files, local_bytes=local.__getitem__, deleter=client)
        self.assertEqual(client.objects.get(a_uri), b"recreated")
        self.assertNotIn(a_uri, client.removed)

    def test_delete_of_move_destination_retains_all_cleanup_targets(self):
        a_uri = sync_garden.uri_for("wiki/a.md")
        b_uri = sync_garden.uri_for("wiki/b.md")
        files = {
            "wiki/b.md": metadata(
                "wiki/b.md", status="pending", task_id="move-task", cleanup_uris=[a_uri],
                cleanup_sources={a_uri: "wiki/a.md"}
            )
        }
        client = ResourceClient({a_uri: b"same", b_uri: b"same"})

        def missing(relative):
            raise FileNotFoundError(relative)

        with patch.object(sync_garden, "scan", return_value={}):
            sync_garden.reconcile_pending(client, files, local_bytes=missing, deleter=client)
            result = sync_garden.apply_changes(
                client, sync_garden.plan_changes(files, {}), files, {}, wait=False, deleter=client
            )
        self.assertEqual(client.objects, {})
        self.assertEqual(result, {})

    def test_waited_upload_cannot_complete_with_stale_scan_digest(self):
        class UploadClient:
            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                return {"queue_status": {"Embedding": {"error_count": 0}}}

            def download_bytes(self, uri):
                return b"changed-after-scan"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/a.md").write_bytes(b"changed-after-scan")
            with patch.object(sync_garden, "GARDEN_ROOT", root):
                result = sync_garden.submission_entry(
                    UploadClient(), "wiki/a.md", metadata("wiki/a.md", b"scanned"), wait=True
                )
        self.assertNotEqual(result["status"], "completed")

    def test_semantically_failed_delete_keeps_retry_state(self):
        relative = "wiki/a.md"
        uri = sync_garden.uri_for(relative)
        old = {relative: metadata(relative, status="completed")}
        client = ResourceClient({uri: b"same"}, deletion_status="failed")
        checkpoints = []
        with patch.object(sync_garden, "scan", return_value={}):
            try:
                result = sync_garden.apply_changes(
                    client,
                    {"add": [], "modify": [], "move": [], "delete": [relative]},
                    old,
                    {},
                    wait=False,
                    deleter=client,
                    checkpoint=lambda files: checkpoints.append(copy.deepcopy(files)),
                )
            except RuntimeError:
                self.assertTrue(checkpoints, "Deletion must be checkpointed before remote mutation")
                result = checkpoints[-1]
        self.assertIn(relative, result)
        self.assertNotEqual(sync_garden.sync_exit_code(result), 0)


class ManifestScopeTests(IsolatedGardenTests):
    def test_manifest_rejects_noncanonical_paths_without_normalizing(self):
        for relative in (
            "wiki", "resources", "../wiki/a.md", "/wiki/a.md", "wiki/../resources/a.md",
            "wiki/./a.md", "wiki//a.md", "wiki/a.md/", "wiki\\a.md",
            "wiki/%2e%2e/a.md", "wiki/a%2fb.md", "wiki/a%5Cb.md", "other/a.md",
        ):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                sync_garden.normalize_manifest({"version": 2, "files": {
                    relative: {"sha256": sync_garden.hash_bytes(b"fixture"), "uri": sync_garden.BASE_URI + "/" + relative,
                               "text": True, "status": "completed"}
                }})

    def test_cleanup_requires_canonical_exact_source_not_a_root_or_destination(self):
        destination = "wiki/sub/b.md"
        for suffix in (
            "", "/wiki", "/resources", "/wiki/../resources/a.md", "/wiki//a.md",
            "/wiki/%2e%2e/a.md", "/wiki/a%2Fb.md", "/wiki/a%5Cb.md",
            "/wiki/a%252fb.md", "/wiki/sub", "/wiki/sub/b.md",
        ):
            uri = sync_garden.BASE_URI + suffix
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                sync_garden.normalize_manifest({"version": 2, "files": {
                    destination: metadata(destination, status="completed", cleanup_uris=[uri])
                }})

    def test_cleanup_source_mapping_must_match_the_target_exactly(self):
        uri = sync_garden.uri_for("wiki/a.md")
        files = {"wiki/b.md": metadata("wiki/b.md", status="pending", cleanup_uris=[uri],
                                       cleanup_sources={uri: "wiki/c.md"})}
        with self.assertRaises(ValueError):
            sync_garden.normalize_manifest({"version": 2, "files": files})

    def test_legacy_cleanup_without_source_proof_stays_recoverable_and_unhealthy(self):
        uri = sync_garden.uri_for("wiki/a.md")
        files = {"wiki/b.md": metadata("wiki/b.md", status="completed", cleanup_uri=uri)}
        normalized = sync_garden.normalize_manifest({"version": 2, "files": files})
        entry = normalized["files"]["wiki/b.md"]
        self.assertEqual(entry["cleanup_uris"], [uri])
        self.assertEqual(entry["status"], "failed")
        self.assertIn("source", entry["failure"])
        self.assertEqual(sync_garden.sync_exit_code(normalized["files"]), 1)

    def test_completed_manifest_without_cleanup_remains_noop(self):
        files = {"wiki/a.md": metadata("wiki/a.md", status="completed")}
        normalized = sync_garden.normalize_manifest({"version": 2, "files": copy.deepcopy(files)})
        self.assertEqual(normalized, {"version": 2, "files": files})
        self.assertEqual(sync_garden.plan_changes(normalized["files"], files),
                         {"add": [], "modify": [], "move": [], "delete": []})
        self.assertEqual(sync_garden.sync_exit_code(normalized["files"]), 0)

    def test_nonempty_cleanup_obligations_cannot_report_success(self):
        uri = sync_garden.uri_for("wiki/a.md")
        files = {"wiki/b.md": metadata("wiki/b.md", status="completed", cleanup_uris=[uri])}
        self.assertEqual(sync_garden.sync_exit_code(files), 1)

    def test_new_move_records_exact_source_identity(self):
        class UploadClient:
            def write(self, uri, content, mode="replace", wait=False, **kwargs):
                return {}

            def download_bytes(self, uri):
                return b"same"

        old = {"wiki/a.md": metadata("wiki/a.md", status="completed")}
        current = {"wiki/b.md": metadata("wiki/b.md")}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wiki").mkdir()
            (root / "wiki/b.md").write_bytes(b"same")
            with patch.object(sync_garden, "GARDEN_ROOT", root):
                result = sync_garden.apply_changes(UploadClient(), sync_garden.plan_changes(old, current),
                                                   old, current, wait=False)
        self.assertEqual(result["wiki/b.md"].get("cleanup_sources"),
                         {sync_garden.uri_for("wiki/a.md"): "wiki/a.md"})


class HTTPResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def deletion_payload(uri, **overrides):
    return {"status": "ok", "result": {
        "uri": uri, "semantic_root_uri": uri.rsplit("/", 1)[0], "semantic_status": "complete",
        "queue_status": {"Embedding": {"error_count": 0, "errors": []}}, **overrides,
    }}


def not_found():
    return HTTPError("http://fixture.invalid/api/v1/fs", 404, "Not found", Message(), io.BytesIO(b"{}"))


class DeletionHTTPTests(unittest.TestCase):
    def adapter(self):
        adapter_type = getattr(sync_garden, "GardenDeletionHTTP", None)
        self.assertIsNotNone(adapter_type, "Deletion must use the Garden public HTTP adapter")
        assert adapter_type is not None
        return adapter_type("http://fixture.invalid:1934")

    def test_delete_retains_terminal_complete_result_and_checks_exact_absence(self):
        uri = sync_garden.uri_for("wiki/中文 note.md")
        payload = deletion_payload(uri)
        with patch("urllib.request.OpenerDirector.open", side_effect=[HTTPResponse(payload), not_found()]) as request:
            result = self.adapter().delete(uri)
        self.assertEqual(result, payload["result"])
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 610)
            headers = {key.lower(): value for key, value in call.args[0].header_items()}
            self.assertEqual(headers["x-openviking-account"], "default")
            self.assertEqual(headers["x-openviking-user"], "gwen")
            self.assertEqual(headers["x-openviking-actor-peer"], "hermes")
            self.assertEqual(urlsplit(call.args[0].full_url).netloc, "fixture.invalid:1934")
            self.assertEqual(parse_qs(urlsplit(call.args[0].full_url).query)["uri"], [uri])
        delete = request.call_args_list[0].args[0]
        self.assertEqual(delete.get_method(), "DELETE")
        self.assertEqual(urlsplit(delete.full_url).path, "/api/v1/fs")
        self.assertEqual(parse_qs(urlsplit(delete.full_url).query),
                         {"uri": [uri], "recursive": ["true"], "wait": ["true"], "timeout": ["600"]})
        readback = request.call_args_list[1].args[0]
        self.assertEqual(readback.get_method(), "GET")
        self.assertEqual(urlsplit(readback.full_url).path, "/api/v1/fs/stat")

    def test_delete_rejects_physical_not_found_without_claiming_semantic_success(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=not_found()) as request:
            with self.assertRaisesRegex(RuntimeError, "semantic.*unverified|recovery"):
                self.adapter().delete(sync_garden.uri_for("wiki/a.md"))
        self.assertEqual(request.call_count, 1)

    def test_delete_rejects_failed_pending_and_unknown_semantic_status(self):
        uri = sync_garden.uri_for("wiki/a.md")
        for status in ("failed", "pending", "unknown", None):
            with self.subTest(status=status), patch("urllib.request.OpenerDirector.open", side_effect=[
                HTTPResponse(deletion_payload(uri, semantic_status=status)), not_found(),
            ]) as request:
                with self.assertRaises(RuntimeError):
                    self.adapter().delete(uri)
                self.assertEqual(request.call_count, 1)

    def test_delete_rejects_queue_errors_even_if_error_count_is_zero(self):
        uri = sync_garden.uri_for("wiki/a.md")
        for queue in (
            {"Embedding": {"error_count": 1}}, {"Embedding": {"error_count": 0, "errors": ["failed"]}},
            {"Semantic": {"error_count": -1}}, {"Semantic": {"pending": 1}}, [], None,
            {"Semantic": {"status": "failed"}}, {"Embedding": {"status": "pending"}},
            {"Semantic": {"nested": {"error_count": 1}}},
        ):
            with self.subTest(queue=queue), patch("urllib.request.OpenerDirector.open", side_effect=[
                HTTPResponse(deletion_payload(uri, queue_status=queue)), not_found(),
            ]) as request:
                with self.assertRaises(RuntimeError):
                    self.adapter().delete(uri)
                self.assertEqual(request.call_count, 1)

    def test_delete_rejects_malformed_or_wrong_scope_result(self):
        uri = sync_garden.uri_for("wiki/a.md")
        for payload in (
            None, [], {}, {"status": "ok", "result": None}, {"status": "error", "result": {}},
            deletion_payload(sync_garden.uri_for("wiki/b.md")),
            deletion_payload(uri, semantic_root_uri="viking://user/gwen/resources"),
        ):
            with self.subTest(payload=payload), patch("urllib.request.OpenerDirector.open", side_effect=[HTTPResponse(payload), not_found()]) as request:
                with self.assertRaises(RuntimeError):
                    self.adapter().delete(uri)
                self.assertEqual(request.call_count, 1)

    def test_delete_requires_physical_readback_absence(self):
        uri = sync_garden.uri_for("wiki/a.md")
        with patch("urllib.request.OpenerDirector.open", side_effect=[HTTPResponse(deletion_payload(uri)), HTTPResponse([])]):
            with self.assertRaisesRegex(RuntimeError, "physical"):
                self.adapter().delete(uri)

    def test_delete_rejects_unsafe_target_before_http(self):
        with patch("urllib.request.OpenerDirector.open") as request:
            with self.assertRaises(ValueError):
                self.adapter().delete(sync_garden.BASE_URI + "/wiki")
        request.assert_not_called()


class ContentIntegrityTests(IsolatedGardenTests):
    def test_completed_move_checks_scanned_hash_even_if_canonical_body_matches(self):
        a_uri = sync_garden.uri_for("wiki/a.md")
        b_uri = sync_garden.uri_for("wiki/b.md")
        scanned = b"---\nid: scanned\n---\nbody"
        changed = b"---\nid: changed\n---\nbody"
        files = {"wiki/b.md": metadata("wiki/b.md", scanned, status="completed",
                                       cleanup_uris=[a_uri], cleanup_sources={a_uri: "wiki/a.md"})}
        client = ResourceClient({a_uri: scanned, b_uri: b"body"})
        sync_garden.reconcile_pending(client, files, local_bytes=lambda relative: changed)
        self.assertEqual(files["wiki/b.md"]["status"], "failed")
        self.assertEqual(client.removed, [])
        self.assertIn(a_uri, files["wiki/b.md"]["cleanup_uris"])

    def test_waited_upload_checks_hash_after_upload_and_after_readback(self):
        for change_at in ("upload", "readback"):
            with self.subTest(change_at=change_at), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "wiki").mkdir()
                path = root / "wiki/a.md"
                path.write_bytes(b"scanned")

                class UploadClient:
                    def write(self, uri, content, mode="replace", wait=False, **kwargs):
                        if change_at == "upload":
                            path.write_bytes(b"changed")
                        return {"queue_status": {"Embedding": {"error_count": 0}}}

                    def download_bytes(self, uri):
                        if change_at == "readback":
                            path.write_bytes(b"changed")
                            return b"scanned"
                        return b"changed"

                with patch.object(sync_garden, "GARDEN_ROOT", root):
                    entry = sync_garden.submission_entry(
                        UploadClient(), "wiki/a.md", metadata("wiki/a.md", b"scanned"), wait=True)
                self.assertEqual(entry["status"], "failed")
                self.assertEqual(entry["sha256"], sync_garden.hash_bytes(b"scanned"))

    def test_pending_upload_checks_hash_again_after_remote_readback(self):
        uri = sync_garden.uri_for("wiki/a.md")
        content = {"local": b"scanned"}

        class ChangingClient(ResourceClient):
            def download_bytes(self, uri):
                content["local"] = b"changed"
                return b"scanned"

        files = {"wiki/a.md": metadata("wiki/a.md", b"scanned", status="pending", task_id="task")}
        sync_garden.reconcile_pending(ChangingClient({uri: b"scanned"}), files,
                                      local_bytes=lambda relative: content["local"])
        self.assertEqual(files["wiki/a.md"]["status"], "failed")

    def test_binary_comparison_remains_exact(self):
        original = b"---\nid: a\n---\nbody\x00"
        stripped = b"body\x00"
        self.assertFalse(sync_garden.remote_content_matches(original, stripped, text=False))
        self.assertTrue(sync_garden.remote_content_matches(original, original, text=False))


class CleanupOccupancyTests(IsolatedGardenTests):
    def move(self):
        a_uri, b_uri = (sync_garden.uri_for("wiki/" + name + ".md") for name in ("a", "b"))
        (self.root / "wiki/b.md").write_bytes(b"same")
        files = {"wiki/b.md": metadata("wiki/b.md", status="completed", cleanup_uris=[a_uri],
                                       cleanup_sources={a_uri: "wiki/a.md"})}
        return a_uri, files, ResourceClient({a_uri: b"same", b_uri: b"same"})

    def test_scan_only_reoccupation_releases_obsolete_claim_after_verification(self):
        a_uri, files, client = self.move()
        (self.root / "wiki/a.md").write_bytes(b"new")
        client.objects[a_uri] = b"new"
        sync_garden.reconcile_pending(client, files, current=sync_garden.scan(), deleter=client)
        self.assertEqual(client.objects.get(a_uri), b"new")
        self.assertEqual(client.removed, [])
        self.assertNotIn("cleanup_uris", files["wiki/b.md"])
        self.assertEqual(files["wiki/b.md"]["status"], "completed")

    def test_manifest_ancestor_descendant_and_exact_collisions_protect_targets(self):
        for occupied, source in (("wiki/a.md", "wiki/a.md"), ("wiki/a", "wiki/a/old.md"),
                                 ("wiki/a.md/child.md", "wiki/a.md")):
            with self.subTest(occupied=occupied):
                _, files, client = self.move()
                uri = sync_garden.uri_for(source)
                files["wiki/b.md"]["cleanup_uris"] = [uri]
                files["wiki/b.md"]["cleanup_sources"] = {uri: source}
                files[occupied] = metadata(occupied, status="completed")
                client.objects[uri] = b"occupied"
                sync_garden.reconcile_pending(client, files, current=sync_garden.scan(), deleter=client)
                self.assertEqual(client.objects.get(uri), b"occupied")
                self.assertNotIn(uri, client.removed)
                self.assertNotIn("cleanup_uris", files["wiki/b.md"])

    def test_reoccupation_after_checkpoint_is_checked_immediately_before_delete(self):
        a_uri, files, client = self.move()
        current = sync_garden.scan()
        checkpoints = []

        def checkpoint(state):
            checkpoints.append(copy.deepcopy(state))
            (self.root / "wiki/a.md").write_bytes(b"late")
            client.objects[a_uri] = b"late"

        sync_garden.reconcile_pending(client, files, current=current, deleter=client, checkpoint=checkpoint)
        self.assertTrue(checkpoints)
        self.assertEqual(client.objects.get(a_uri), b"late")
        self.assertEqual(client.removed, [])

    def test_symlink_and_directory_reoccupation_is_not_absence(self):
        for kind in ("symlink", "directory"):
            with self.subTest(kind=kind):
                a_uri, files, client = self.move()
                path = self.root / "wiki/a.md"
                if kind == "symlink":
                    path.symlink_to(self.root / "missing")
                else:
                    path.mkdir()
                try:
                    sync_garden.reconcile_pending(client, files, current=sync_garden.scan(), deleter=client)
                    self.assertIn(a_uri, client.objects)
                    self.assertEqual(client.removed, [])
                finally:
                    if kind == "symlink":
                        path.unlink()
                    else:
                        path.rmdir()

    def test_local_permission_errors_hold_cleanup_in_failed_state(self):
        a_uri, files, client = self.move()
        current = sync_garden.scan()
        original = Path.lstat

        def denied(path, *args, **kwargs):
            if path == self.root / "wiki/a.md":
                raise PermissionError("fixture permission denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "lstat", denied):
            sync_garden.reconcile_pending(client, files, current=current, deleter=client)
        self.assertEqual(client.removed, [])
        self.assertEqual(files["wiki/b.md"]["status"], "failed")
        self.assertEqual(files["wiki/b.md"]["cleanup_uris"], [a_uri])

    def test_legacy_unproven_cleanup_is_not_deleted_even_without_normalization(self):
        a_uri, files, client = self.move()
        files["wiki/b.md"].pop("cleanup_sources")
        sync_garden.reconcile_pending(client, files, current=sync_garden.scan(), deleter=client)
        self.assertEqual(client.removed, [])
        self.assertEqual(files["wiki/b.md"]["status"], "failed")
        self.assertEqual(files["wiki/b.md"]["cleanup_uris"], [a_uri])

    def test_lexical_prefix_neighbor_does_not_block_exact_cleanup(self):
        a_uri, files, client = self.move()
        files["wiki/a.md-other"] = metadata("wiki/a.md-other", status="completed")
        client.objects[sync_garden.uri_for("wiki/a.md-other")] = b"neighbor"
        sync_garden.reconcile_pending(client, files, current=sync_garden.scan(), deleter=client)
        self.assertEqual(client.removed, [a_uri])
        self.assertIn(sync_garden.uri_for("wiki/a.md-other"), client.objects)


class DeletionTombstoneTests(IsolatedGardenTests):
    def move(self):
        a_uri, b_uri = (sync_garden.uri_for("wiki/" + name + ".md") for name in ("a", "b"))
        files = {"wiki/b.md": metadata("wiki/b.md", status="pending", task_id="task",
                                       cleanup_uris=[a_uri], cleanup_sources={a_uri: "wiki/a.md"})}
        return a_uri, b_uri, files, ResourceClient({a_uri: b"same", b_uri: b"same"})

    def test_missing_destination_becomes_checkpointed_tombstone_only_after_terminal_task(self):
        a_uri, b_uri, files, client = self.move()
        client.task_state = "running"
        checkpoints = []
        checkpoint = lambda state: checkpoints.append(copy.deepcopy(state))
        sync_garden.reconcile_pending(client, files, current={}, deleter=client, checkpoint=checkpoint)
        self.assertEqual(client.removed, [])
        self.assertEqual(files["wiki/b.md"]["status"], "pending")
        self.assertFalse(files["wiki/b.md"].get("delete_pending"))
        client.task_state = "completed"
        sync_garden.reconcile_pending(client, files, current={}, deleter=client, checkpoint=checkpoint)
        self.assertTrue(checkpoints)
        self.assertTrue(files["wiki/b.md"].get("delete_pending"))
        self.assertEqual(set(files["wiki/b.md"]["cleanup_uris"]), {a_uri, b_uri})
        self.assertNotEqual(files["wiki/b.md"]["status"], "completed")
        result = sync_garden.apply_changes(client, sync_garden.plan_changes(files, {}), files, {}, wait=False,
                                           deleter=client, checkpoint=checkpoint)
        self.assertEqual(result, {})
        self.assertEqual(client.objects, {})

    def test_partial_semantic_failure_checkpoints_each_target_and_does_not_retry_delete(self):
        a_uri, b_uri, files, client = self.move()
        client.semantic_by_uri[a_uri] = "failed"
        checkpoints = []
        checkpoint = lambda state: checkpoints.append(copy.deepcopy(state))
        sync_garden.reconcile_pending(client, files, current={}, deleter=client, checkpoint=checkpoint)
        result = sync_garden.apply_changes(client, sync_garden.plan_changes(files, {}), files, {}, wait=False,
                                           deleter=client, checkpoint=checkpoint)
        self.assertIn("wiki/b.md", result)
        entry = result["wiki/b.md"]
        self.assertTrue(entry.get("delete_pending"))
        self.assertEqual(entry["cleanup_uris"], [a_uri])
        self.assertEqual(entry["cleanup_sources"], {a_uri: "wiki/a.md"})
        self.assertEqual(entry["status"], "failed")
        self.assertTrue(any(set(state["wiki/b.md"].get("cleanup_uris", [])) == {a_uri, b_uri}
                            for state in checkpoints if "wiki/b.md" in state))
        attempts = list(client.removed)
        recovered = sync_garden.normalize_manifest({"version": 2, "files": copy.deepcopy(result)})["files"]
        sync_garden.reconcile_pending(client, recovered, current={}, deleter=client, checkpoint=checkpoint)
        again = sync_garden.apply_changes(client, sync_garden.plan_changes(recovered, {}), recovered, {},
                                          wait=False, deleter=client, checkpoint=checkpoint)
        self.assertEqual(client.removed, attempts)
        self.assertIn(a_uri, again["wiki/b.md"]["cleanup_uris"])
        self.assertEqual(sync_garden.sync_exit_code(again), 1)

    def test_reoccupied_unresolved_target_cancels_claim_without_deleting_new_resource(self):
        a_uri, b_uri, files, client = self.move()
        client.semantic_by_uri[a_uri] = "failed"
        sync_garden.reconcile_pending(client, files, current={}, deleter=client)
        files = sync_garden.apply_changes(client, sync_garden.plan_changes(files, {}), files, {}, wait=False,
                                          deleter=client)
        self.assertIn("wiki/b.md", files)
        self.assertEqual(files["wiki/b.md"]["cleanup_uris"], [a_uri])
        (self.root / "wiki/a.md").write_bytes(b"recreated")
        client.objects[a_uri] = b"recreated"
        attempts = list(client.removed)
        sync_garden.reconcile_pending(client, files, current=sync_garden.scan(), deleter=client)
        self.assertEqual(client.removed, attempts)
        self.assertEqual(client.objects[a_uri], b"recreated")
        self.assertEqual(files, {})


    def test_failed_move_cleanup_does_not_resubmit_unchanged_destination(self):
        a_uri, b_uri, files, client = self.move()
        (self.root / "wiki/b.md").write_bytes(b"same")
        client.semantic_by_uri[a_uri] = "failed"
        current = sync_garden.scan()
        sync_garden.reconcile_pending(client, files, current=current, deleter=client)
        self.assertNotIn(a_uri, client.objects)
        self.assertEqual(files["wiki/b.md"]["status"], "failed")
        self.assertEqual(sync_garden.plan_changes(files, current)["modify"], [])


class ReadbackScopeTests(IsolatedGardenTests):
    def test_readback_preserves_the_sdk_literal_unicode_child_uri(self):
        uri = sync_garden.uri_for("wiki/算法复习.md")
        child = uri + "/算法复习.md"
        reads = []

        class Client:
            def download_bytes(self, target):
                reads.append(target)
                if target == child:
                    return b"body from actual SDK URI"
                raise FileNotFoundError(target)

            def ls(self, target, **kwargs):
                return [{"uri": child, "name": "算法复习.md", "isDir": False}]

        actual = sync_garden.remote_resource_bytes(Client(), uri, "算法复习.md")
        self.assertEqual(actual, b"body from actual SDK URI")
        self.assertEqual(reads, [uri, child])

    def test_symlinked_garden_root_cannot_authorize_upload(self):
        (self.root / "wiki/a.md").write_bytes(b"same")
        alias = self.root / "garden-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with patch.object(sync_garden, "GARDEN_ROOT", alias), self.assertRaises(ValueError):
            sync_garden.checked_local_path("wiki/a.md")

    def test_upload_rejects_literal_path_aliases_and_wrong_target(self):
        (self.root / "wiki/a.md").write_bytes(b"same")

        class UploadClient:
            def add_resource(self, path, **kwargs):
                return {"task_id": "task"}

        for relative, uri in (("wiki/./a.md", sync_garden.uri_for("wiki/a.md")),
                              ("wiki//a.md", sync_garden.uri_for("wiki/a.md")),
                              ("wiki/a.md", "viking://user/other/resources/a")):
            with self.subTest(relative=relative, uri=uri), self.assertRaises(ValueError):
                sync_garden.submission_entry(UploadClient(), relative, metadata("wiki/a.md", uri=uri), wait=False)

    def test_tree_readback_rejects_out_of_scope_or_aliased_children(self):
        uri = sync_garden.uri_for("wiki/b.md")
        for child in (sync_garden.uri_for("wiki/a.md"), "viking://user/other/resources/a.md",
                      uri + "/../a.md", uri + "/%2e%2e/a.md", uri + "/a%2fb.md",
                      uri + "/a%252fb.md", uri + "/a\\b.md", uri + "/./a.md", uri + "-other/a.md"):
            with self.subTest(child=child):
                reads = []

                class Client:
                    def download_bytes(self, target):
                        reads.append(target)
                        return None if target == uri else b"same"

                    def ls(self, target, **kwargs):
                        return [{"uri": child, "name": "b.md", "isDir": False}]

                self.assertIsNone(sync_garden.remote_resource_bytes(Client(), uri, "b.md"))
                self.assertEqual(reads, [uri])

    def test_readback_rejects_unscoped_root_before_reading(self):
        class Client:
            def download_bytes(self, uri):
                return b"same"

        with self.assertRaises(ValueError):
            sync_garden.remote_resource_bytes(Client(), "viking://outside/a.md", "a.md")

    def test_malformed_tree_listing_cannot_supply_completion_evidence(self):
        uri = sync_garden.uri_for("wiki/b.md")

        class Client:
            def download_bytes(self, target):
                return None if target == uri else b"same"

            def ls(self, target, **kwargs):
                return ["malformed", {"uri": uri + "/b.md", "isDir": False}]

        self.assertIsNone(sync_garden.remote_resource_bytes(Client(), uri, "b.md"))


class RestartAndRenameTests(IsolatedGardenTests):
    class UploadClient(ResourceClient):
        def __init__(self, objects):
            super().__init__(objects)
            self.submitted = []

        def add_resource(self, path, **kwargs):
            self.submitted.append(kwargs["to"])
            self.objects[kwargs["to"]] = Path(path).read_bytes()
            return {"task_id": "replacement-task"}

    def test_upload_intent_retains_all_cleanup_provenance_before_submission(self):
        prior = [sync_garden.uri_for("wiki/prior.md"), sync_garden.uri_for("wiki/prior2.md")]
        sources = dict(zip(prior, ("wiki/prior.md", "wiki/prior2.md")))
        attempts = {uri: "semantic recovery required" for uri in prior}
        for action in ("modify", "move"):
            with self.subTest(action=action):
                source = "wiki/a.md" if action == "move" else "wiki/b.md"
                old = {source: metadata(source, b"B" if action == "move" else b"A", status="failed",
                                         cleanup_uris=prior, cleanup_sources=sources, cleanup_attempts=attempts)}
                (self.root / "wiki/b.md").write_bytes(b"B")
                current = {"wiki/b.md": metadata("wiki/b.md", b"B")}
                checkpoints, at_submit = [], []
                client = MagicMock()

                def interrupted(*args, **kwargs):
                    at_submit.append(copy.deepcopy(checkpoints[-1]) if checkpoints else {})
                    raise TimeoutError("fixture accepted upload; response lost")

                client.write.side_effect = interrupted
                with self.assertRaises(TimeoutError):
                    sync_garden.apply_changes(
                        client, sync_garden.plan_changes(old, current), old, current, wait=False,
                        checkpoint=lambda state: checkpoints.append(copy.deepcopy(state)),
                    )
                self.assertEqual(len(at_submit), 1)
                self.assertIn("wiki/b.md", at_submit[0])
                intent = at_submit[0]["wiki/b.md"]
                self.assertEqual(intent["sha256"], current["wiki/b.md"]["sha256"])
                self.assertNotEqual(intent["status"], "completed")
                self.assertIn("task_id", intent)
                self.assertIsNone(intent["task_id"])
                expected_sources = {**sources, **({sync_garden.uri_for(source): source} if action == "move" else {})}
                self.assertEqual(intent["cleanup_uris"], list(expected_sources))
                self.assertEqual(intent["cleanup_sources"], expected_sources)
                self.assertEqual(intent["cleanup_attempts"], attempts)
                self.assertEqual(checkpoints[-1], at_submit[0])
                if action == "move":
                    self.assertNotIn(source, at_submit[0])

    def test_chained_and_reverse_moves_preserve_exact_provenance(self):
        for destination in ("wiki/c.md", "wiki/a.md"):
            with self.subTest(destination=destination):
                a_uri, b_uri = sync_garden.uri_for("wiki/a.md"), sync_garden.uri_for("wiki/b.md")
                files = {"wiki/b.md": metadata("wiki/b.md", status="failed", cleanup_uris=[a_uri],
                                               cleanup_sources={a_uri: "wiki/a.md"})}
                path = self.root / destination
                path.write_bytes(b"same")
                current = {destination: metadata(destination)}
                client = self.UploadClient({a_uri: b"same", b_uri: b"same"})
                result = sync_garden.apply_changes(client, sync_garden.plan_changes(files, current), files, current,
                                                   wait=False, deleter=client)
                sources = {b_uri: "wiki/b.md"}
                if destination != "wiki/a.md":
                    sources[a_uri] = "wiki/a.md"
                self.assertEqual(result[destination]["cleanup_sources"], sources)
                result = sync_garden.normalize_manifest({"version": 2, "files": result})["files"]
                sync_garden.reconcile_pending(client, result, current=current, deleter=client)
                self.assertEqual(result[destination]["status"], "completed")
                self.assertEqual(client.objects, {sync_garden.uri_for(destination): b"same"})
                self.assertNotIn("cleanup_uris", result[destination])
                path.unlink()

    def test_overlapping_rename_is_not_an_unsafe_ancestor_cleanup_claim(self):
        old = {"wiki/a.md": metadata("wiki/a.md", status="completed")}
        current = {"wiki/a.md/child.md": metadata("wiki/a.md/child.md")}
        self.assertEqual(sync_garden.plan_changes(old, current)["move"], [])

    def test_original_active_or_unknown_upload_is_not_lost_on_move_or_modify(self):
        for task_state in ("running", "missing"):
            for action in ("move", "modify"):
                with self.subTest(task_state=task_state, action=action):
                    old = {"wiki/b.md": metadata("wiki/b.md", status="failed", task_id="original-task")}
                    destination = "wiki/c.md" if action == "move" else "wiki/b.md"
                    path = self.root / destination
                    path.write_bytes(b"same")
                    current = {destination: metadata(destination)}
                    client = self.UploadClient({sync_garden.uri_for("wiki/b.md"): b"same"})
                    client.task_state = task_state
                    changes = {"add": [], "modify": [], "move": [], "delete": []}
                    changes[action] = [("wiki/b.md", destination)] if action == "move" else [destination]
                    result = sync_garden.apply_changes(client, changes, old, current, wait=False, deleter=client)
                    self.assertEqual(client.submitted, [])
                    self.assertIn("wiki/b.md", result)
                    self.assertEqual(result["wiki/b.md"]["task_id"], "original-task")
                    self.assertEqual(client.removed, [])
                    path.unlink()

    def test_unidentified_accepted_upload_cannot_be_deleted_on_retry(self):
        class Client(ResourceClient):
            def add_resource(self, path, **kwargs):
                return {}

        uri = sync_garden.uri_for("wiki/a.txt")
        path = self.root / "wiki/a.txt"
        path.write_bytes(b"same")
        client = Client({uri: b"same"})
        entry = sync_garden.submission_entry(client, "wiki/a.txt", metadata("wiki/a.txt"), wait=False)
        path.unlink()
        files = {"wiki/a.txt": entry}
        for _ in range(2):
            files = sync_garden.apply_changes(client, sync_garden.plan_changes(files, {}), files, {},
                                              wait=False, deleter=client)
        self.assertEqual(client.removed, [])
        self.assertIn("wiki/a.txt", files)
        self.assertEqual(sync_garden.sync_exit_code(files), 1)

    def test_crash_after_remote_delete_leaves_a_recoverable_attempt_before_restart(self):
        class InterruptedClient(ResourceClient):
            def delete(self, uri):
                super().delete(uri)
                raise SystemExit("fixture interruption after remote mutation")

        uri = sync_garden.uri_for("wiki/a.md")
        old = {"wiki/a.md": metadata("wiki/a.md", status="completed")}
        client = InterruptedClient({uri: b"same"})
        checkpoints = []
        with self.assertRaises(SystemExit):
            sync_garden.apply_changes(client, sync_garden.plan_changes(old, {}), old, {}, wait=False,
                                      deleter=client, checkpoint=lambda state: checkpoints.append(copy.deepcopy(state)))
        self.assertTrue(checkpoints)
        saved = checkpoints[-1]
        self.assertTrue(saved["wiki/a.md"]["delete_pending"])
        self.assertEqual(saved["wiki/a.md"]["cleanup_uris"], [uri])
        self.assertIn(uri, saved["wiki/a.md"]["cleanup_attempts"])
        recovered = sync_garden.normalize_manifest({"version": 2, "files": saved})["files"]
        sync_garden.reconcile_pending(client, recovered, current={}, deleter=client)
        self.assertEqual(client.removed, [uri])
        self.assertEqual(sync_garden.sync_exit_code(recovered), 1)
        self.assertIn("recovery", recovered["wiki/a.md"]["failure"])


class SyncEntrypointTests(IsolatedGardenTests):
    def run_main(self, client, *, wait=False):
        with patch.object(sync_garden, "MANIFEST_PATH", self.root / "manifest.json"), \
                patch.object(sync_garden, "PENDING_SNAPSHOT_PATH", self.root / "pending.json"), \
                patch.object(sync_garden, "SyncHTTPClient", return_value=client), \
                patch("sys.argv", ["sync_garden.py", "--url", "http://fixture.invalid:2999", *(["--wait"] if wait else [])]), \
                redirect_stdout(io.StringIO()):
            return sync_garden.main()

    def test_ambiguous_upload_intent_is_durable_and_retry_cannot_mutate_resources(self):
        for action in ("add", "modify", "move"):
            for failure in (TimeoutError, SystemExit, AttributeError):
                for wait in (False, True):
                    with self.subTest(action=action, failure=failure.__name__, wait=wait):
                        relative = "wiki/b.md"
                        source = "wiki/a.md" if action == "move" else relative
                        old = {} if action == "add" else {
                            source: metadata(source, b"B" if action == "move" else b"A", status="completed")
                        }
                        path = self.root / relative
                        path.write_bytes(b"B")
                        state = self.root / "manifest.json"
                        state.write_text(json.dumps({"version": 2, "files": old}), encoding="utf-8")
                        (self.root / "pending.json").unlink(missing_ok=True)
                        client = MagicMock()
                        client.snapshot.log.return_value = []
                        client.snapshot.commit.return_value = {"result": "created", "commit_oid": "fixture-snapshot"}
                        client.get_task.return_value = None
                        remote = {entry["uri"]: b"A" for entry in old.values()}
                        at_submit = []

                        def accepted(uri, content, **kwargs):
                            at_submit.append(json.loads(state.read_text(encoding="utf-8"))["files"])
                            remote[uri] = path.read_bytes()
                            if failure is AttributeError:
                                return ["malformed response"]
                            raise failure("fixture accepted upload; response lost")

                        client.write.side_effect = accepted
                        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("unexpected HTTP")) as request:
                            with self.assertRaises(failure):
                                self.run_main(client, wait=wait)
                            client.write.assert_called_once()
                            client.close.assert_called_once()
                            saved = json.loads(state.read_text(encoding="utf-8"))["files"]
                            self.assertEqual(saved, at_submit[0])
                            self.assertIn(relative, saved)
                            intent = saved[relative]
                            for key, value in metadata(relative, b"B").items():
                                self.assertEqual(intent[key], value)
                            self.assertNotEqual(intent["status"], "completed")
                            self.assertIn("task_id", intent)
                            self.assertIsNone(intent["task_id"])
                            if action == "move":
                                self.assertNotIn(source, saved)
                                self.assertEqual(intent["cleanup_uris"], [sync_garden.uri_for(source)])
                                self.assertEqual(intent["cleanup_sources"], {sync_garden.uri_for(source): source})
                            accepted_remote = dict(remote)
                            recovery = (self.root / "pending.json").read_bytes()
                            for local in (b"A", None, None):
                                if local is None:
                                    path.unlink(missing_ok=True)
                                else:
                                    path.write_bytes(local)
                                client.reset_mock()
                                client.write.side_effect = AssertionError("unknown upload must not be resubmitted")
                                self.assertEqual(self.run_main(client, wait=wait), 1)
                                client.write.assert_not_called()
                                client.rm.assert_not_called()
                                client.download_bytes.assert_not_called()
                                client.get_task.assert_not_called()
                                client.snapshot.commit.assert_not_called()
                                self.assertEqual((self.root / "pending.json").read_bytes(), recovery)
                                retried = json.loads(state.read_text(encoding="utf-8"))["files"][relative]
                                self.assertEqual(retried["sha256"], intent["sha256"])
                                self.assertIn("task_id", retried)
                                self.assertIsNone(retried["task_id"])
                                self.assertNotEqual(retried["status"], "completed")
                                self.assertEqual(remote, accepted_remote)
                            request.assert_not_called()

    def test_waited_upload_without_task_id_allows_later_modify_and_delete(self):
        relative = "wiki/a.md"
        uri = sync_garden.uri_for(relative)
        path = self.root / relative
        state = self.root / "manifest.json"
        remote = {}
        client, deleter = MagicMock(), MagicMock()
        client.snapshot.log.return_value = []
        client.snapshot.commit.return_value = {"result": "created", "commit_oid": "fixture-snapshot"}

        def accepted(uri, content, **kwargs):
            remote[uri] = content.encode("utf-8") if isinstance(content, str) else content
            return {"queue_status": {"Embedding": {"error_count": 0}}}

        client.write.side_effect = accepted
        client.download_bytes.side_effect = remote.get
        deleter.delete.side_effect = remote.pop
        with patch.object(sync_garden, "GardenDeletionHTTP", return_value=deleter), \
                patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("unexpected HTTP")) as request:
            for content in (b"A", b"B"):
                path.write_bytes(content)
                self.assertEqual(self.run_main(client, wait=True), 0)
                entry = json.loads(state.read_text(encoding="utf-8"))["files"][relative]
                self.assertEqual(entry["status"], "completed")
                self.assertEqual(entry["sha256"], sync_garden.hash_bytes(content))
                self.assertNotIn("task_id", entry)
                self.assertEqual(remote[uri], content)
            self.assertEqual(client.write.call_count, 2)
            path.unlink()
            self.assertEqual(self.run_main(client, wait=True), 0)
            deleter.delete.assert_called_once_with(uri)
            self.assertEqual(remote, {})
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["files"], {})
            client.get_task.assert_not_called()
            request.assert_not_called()

    def test_completed_v2_entries_remain_noop_without_cleanup_or_http(self):
        files = {}
        for relative in ("wiki/a.md", "wiki/b.md", "wiki/c.md", "wiki/d.md"):
            (self.root / relative).write_bytes(b"same")
            files[relative] = metadata(relative, status="completed")
        state = self.root / "manifest.json"
        state.write_text(json.dumps({"version": 2, "files": files}), encoding="utf-8")
        client = MagicMock()
        with patch("urllib.request.OpenerDirector.open") as request:
            self.assertEqual(self.run_main(client), 0)
        request.assert_not_called()
        client.add_resource.assert_not_called()
        client.rm.assert_not_called()
        client.snapshot.commit.assert_not_called()
        saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["files"], files)

    def test_semantic_failure_is_durable_and_retry_does_not_mutate(self):
        uri = sync_garden.uri_for("wiki/a.md")
        files = {"wiki/a.md": metadata("wiki/a.md", status="completed")}
        state = self.root / "manifest.json"
        state.write_text(json.dumps({"version": 2, "files": files}), encoding="utf-8")
        client = MagicMock()
        client.snapshot.log.return_value = []
        client.snapshot.commit.return_value = {"result": "created", "commit_oid": "fixture-snapshot"}

        def delete_response(request, **kwargs):
            saved = json.loads(state.read_text(encoding="utf-8"))["files"]["wiki/a.md"]
            self.assertTrue(saved["delete_pending"])
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["cleanup_uris"], [uri])
            self.assertIn(uri, saved["cleanup_attempts"])
            self.assertEqual(request.get_method(), "DELETE")
            self.assertEqual(urlsplit(request.full_url).netloc, "fixture.invalid:2999")
            return HTTPResponse(deletion_payload(uri, semantic_status="failed"))

        with patch("urllib.request.OpenerDirector.open", side_effect=delete_response) as request:
            self.assertEqual(self.run_main(client), 1)
            self.assertEqual(request.call_count, 1)
        saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertTrue(saved["files"]["wiki/a.md"]["delete_pending"])
        self.assertEqual(saved["files"]["wiki/a.md"]["cleanup_sources"], {uri: "wiki/a.md"})
        client.reset_mock()
        with patch("urllib.request.OpenerDirector.open") as request:
            self.assertEqual(self.run_main(client), 1)
        request.assert_not_called()
        client.add_resource.assert_not_called()
        client.rm.assert_not_called()
        client.snapshot.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
