#!/usr/bin/env python3
"""One-way, idempotent Garden to OpenViking synchronizer."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import stat
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlencode

from openviking import SyncHTTPClient
from openviking.parse.parsers.html import HTMLParser as OpenVikingHTMLParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GARDEN_ROOT = PROJECT_ROOT / "garden"
MANIFEST_PATH = PROJECT_ROOT / ".runtime/sync-manifest.json"
PENDING_SNAPSHOT_PATH = PROJECT_ROOT / ".runtime/sync-snapshot-pending.json"
SYNC_ROOTS = ("wiki",)
BASE_URI = os.environ.get("AGENT_GARDEN_VIKING_ROOT", "viking://user/gwen/resources/garden")
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv", ".sh", ".zsh", ".js", ".ts", ".html", ".css"}
SNAPSHOT_AMBIGUOUS_STATUS = (502, 503, 504)


def atomic_state_module():
    spec = importlib.util.spec_from_file_location("atomic_state", PROJECT_ROOT / "automation/atomic_state.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def relative_parts(relative: str) -> tuple[str, ...]:
    """Validate literal source tokens before any pathlib/URI normalization."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("Garden paths must be non-empty strings")
    parts = tuple(relative.split("/"))
    if (len(parts) < 2 or parts[0] not in SYNC_ROOTS
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative or any(ord(char) < 32 or ord(char) == 127 for char in relative)
            or unquote(relative) != relative):
        raise ValueError(f"Refusing noncanonical Garden resource path: {relative!r}")
    return parts


def uri_for(relative: str) -> str:
    encoded = "/".join(quote(part, safe="._-~") for part in relative_parts(relative))
    return f"{BASE_URI}/{encoded}"


def relative_for_uri(uri: object) -> str:
    prefix = BASE_URI + "/"
    if not isinstance(uri, str) or not uri.startswith(prefix):
        raise ValueError("Refusing URI outside Garden root")
    relative = unquote(uri[len(prefix):], errors="strict")
    if uri_for(relative) != uri:
        raise ValueError("Refusing noncanonical Garden resource URI")
    return relative


def validate_delete_uri(uri: str, *, expected: str | None = None, destination: str | None = None) -> str:
    source = relative_parts(relative_for_uri(uri))
    if expected is not None and uri != expected:
        raise ValueError("Refusing deletion of a URI that does not match its manifest path")
    if destination is not None and relative_parts(destination)[:len(source)] == source:
        raise ValueError("Refusing deletion of the destination or its ancestor")
    return uri


def has_scoped_symlink(path: Path, root: Path) -> bool:
    if root.is_symlink():
        return True
    cursor = root
    for part in path.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def scan() -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for root_name in SYNC_ROOTS:
        root = GARDEN_ROOT / root_name
        for path in sorted(root.rglob("*")):
            if has_scoped_symlink(path, GARDEN_ROOT):
                continue
            if not path.is_file() or path.name.startswith(".") or ".obsidian" in path.parts or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(GARDEN_ROOT).as_posix()
            entries[relative] = {
                "sha256": digest(path),
                "uri": uri_for(relative),
                "text": path.suffix.lower() in TEXT_SUFFIXES,
            }
    return entries


def normalize_manifest(data: dict) -> dict:
    files = data.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("sync manifest files must be a mapping")
    for relative, entry in files.items():
        if not isinstance(relative, str) or not relative:
            raise ValueError("sync manifest paths must be non-empty strings")
        if not isinstance(entry, dict):
            raise ValueError("sync manifest entries must be mappings")
        status = entry.setdefault("status", "unverified")
        if status not in {"unverified", "accepted", "pending", "completed", "failed"}:
            entry["status"] = "unverified"
        for key in ("sha256", "uri"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ValueError(f"sync manifest entry {relative!r} requires a non-empty {key}")
        if len(entry["sha256"]) != 64 or any(char not in "0123456789abcdefABCDEF" for char in entry["sha256"]):
            raise ValueError(f"sync manifest entry {relative!r} sha256 must be exactly 64 ASCII hexadecimal characters")
        if entry["uri"] != uri_for(relative):
            raise ValueError(f"sync manifest entry {relative!r} URI does not match its expected path")
        if not isinstance(entry.get("text"), bool):
            raise ValueError(f"sync manifest entry {relative!r} requires a boolean text flag")
        legacy_cleanup = entry.get("cleanup_uri")
        if legacy_cleanup is not None and (not isinstance(legacy_cleanup, str) or not legacy_cleanup):
            raise ValueError("sync manifest cleanup_uri must be a non-empty string")
        cleanup_uris = entry.get("cleanup_uris", [])
        if not isinstance(cleanup_uris, list) or not all(isinstance(uri, str) and uri for uri in cleanup_uris):
            raise ValueError("sync manifest cleanup_uris must be a list of non-empty strings")
        if isinstance(legacy_cleanup, str) and legacy_cleanup:
            cleanup_uris = [*cleanup_uris, legacy_cleanup]
        sources = entry.get("cleanup_sources", {})
        if not isinstance(sources, dict) or set(sources) - set(cleanup_uris):
            raise ValueError("sync manifest cleanup_sources must map cleanup URIs to source paths")
        attempts = entry.get("cleanup_attempts", {})
        if (not isinstance(attempts, dict) or set(attempts) - set(cleanup_uris)
                or any(not isinstance(reason, str) or not reason for reason in attempts.values())):
            raise ValueError("sync manifest cleanup_attempts must retain unresolved deletion results")
        if "delete_pending" in entry and not isinstance(entry["delete_pending"], bool):
            raise ValueError("sync manifest delete_pending must be boolean")
        if entry.get("delete_pending"):
            entry["status"] = "failed"
        for uri in cleanup_uris:
            validate_delete_uri(uri, destination=None if entry.get("delete_pending") and uri == entry["uri"] else relative)
            if uri in sources:
                validate_delete_uri(uri, expected=uri_for(sources[uri]))
        if cleanup_uris:
            entry["cleanup_uris"] = list(dict.fromkeys(cleanup_uris))
            if any(uri not in sources for uri in cleanup_uris):
                entry.update(status="failed", failure="cleanup source identity missing; recovery required")
        entry.pop("cleanup_uri", None)
    return {"version": 2, "files": files}


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"version": 2, "files": {}}
    return normalize_manifest(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def sync_exit_code(files: dict) -> int:
    return int(any(entry.get("status") != "completed" or entry.get("cleanup_uris")
                   or entry.get("cleanup_uri") or entry.get("delete_pending") for entry in files.values()))


def sync_fingerprint(old: dict, new: dict) -> str:
    """Identify one pending Garden mutation without depending on dict ordering."""
    states = {
        "old": {path: entry["sha256"] for path, entry in old.items()},
        "new": {path: entry["sha256"] for path, entry in new.items()},
    }
    encoded = json.dumps(states, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_or_create_snapshot_operation(old: dict, new: dict, *, path: Path | None = None) -> dict:
    """Persist the snapshot identity so an ambiguous request can be reconciled later."""
    pending_path = path or PENDING_SNAPSHOT_PATH
    fingerprint = sync_fingerprint(old, new)
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pending = {}
    if pending.get("fingerprint") == fingerprint and pending.get("message"):
        return pending

    operation_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    pending = {
        "version": 1,
        "operation_id": operation_id,
        "fingerprint": fingerprint,
        "created_at": created_at,
        "message": f"before garden sync op={operation_id} at {created_at}",
    }
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = pending_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, pending_path)
    return pending


def clear_snapshot_operation(operation: dict | None = None, *, path: Path | None = None) -> None:
    """Remove only the pending operation that this process completed."""
    pending_path = path or PENDING_SNAPSHOT_PATH
    if operation is not None:
        try:
            current = json.loads(pending_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if current.get("operation_id") != operation.get("operation_id"):
            return
    pending_path.unlink(missing_ok=True)


def find_snapshot_by_message(client, message: str) -> dict | None:
    """Return an already-created snapshot for this exact sync operation."""
    for entry in client.snapshot.log(branch="main", limit=500):
        if entry.get("message") == message:
            return {
                "result": "created",
                "commit_oid": entry["oid"],
                "recovered": True,
            }
    return None


def commit_snapshot_safely(client, *, message: str) -> dict:
    """Create at most one snapshot, reconciling ambiguous gateway responses by message."""
    existing = find_snapshot_by_message(client, message)
    if existing is not None:
        return existing

    try:
        return client.snapshot.commit(
            message=message,
            author_name="Agent Garden",
            author_email="agent-garden@localhost",
        )
    except Exception as exc:
        ambiguous = any(f"HTTP {status}" in str(exc) for status in SNAPSHOT_AMBIGUOUS_STATUS)
        if not ambiguous:
            raise
        try:
            recovered = find_snapshot_by_message(client, message)
        except Exception:
            recovered = None
        if recovered is not None:
            return recovered
        raise RuntimeError(
            "snapshot response was ambiguous; left the operation pending for a safe later retry"
        ) from exc


def plan_changes(old: dict, new: dict) -> dict:
    old_paths, new_paths = set(old), set(new)
    removed = {
        path for path in old_paths - new_paths
        if old[path].get("status") not in {"accepted", "pending"}
        and not (old[path].get("delete_pending") and old[path].get("cleanup_uris")
                 and all(uri in old[path].get("cleanup_attempts", {}) for uri in old[path]["cleanup_uris"]))
    }
    added = new_paths - old_paths
    modified = {
        path for path in old_paths & new_paths
        if old[path].get("status") not in {"accepted", "pending"}
        and (old[path]["sha256"] != new[path]["sha256"]
             or (old[path].get("status", "unverified") in {"failed", "unverified"}
                 and (not old[path].get("cleanup_attempts") or old[path].get("delete_pending"))))
    }
    moves = []
    by_hash: dict[str, list[str]] = {}
    for path in removed:
        if not old[path].get("delete_pending") and "task_id" not in old[path]:
            by_hash.setdefault(old[path]["sha256"], []).append(path)
    for destination in list(added):
        matches = by_hash.get(new[destination]["sha256"], [])
        if len(matches) == 1 and not paths_overlap(matches[0], destination):
            source = matches[0]
            moves.append((source, destination))
            removed.remove(source)
            added.remove(destination)
            by_hash.pop(new[destination]["sha256"], None)
    return {"add": sorted(added), "modify": sorted(modified), "move": sorted(moves), "delete": sorted(removed)}


def require_clean_queue(status: object) -> None:
    if not isinstance(status, dict):
        raise RuntimeError("OpenViking processing errors: malformed queue status")
    for value in status.values():
        if not isinstance(value, dict):
            raise RuntimeError("OpenViking processing errors: malformed queue entry")
        for key in ("error_count", "pending", "pending_count", "running"):
            if key in value and (type(value[key]) is not int or value[key] != 0):
                raise RuntimeError(f"OpenViking processing errors or unfinished work: {key}={value[key]!r}")
        if value.get("errors") or value.get("error"):
            raise RuntimeError("OpenViking processing errors in queue result")
        if "status" in value and (not isinstance(value["status"], str) or value["status"] not in {
            "complete", "completed", "done", "success", "succeeded", "idle"
        }):
            raise RuntimeError("OpenViking processing errors or nonterminal queue status")
        for nested in value.values():
            if isinstance(nested, dict):
                require_clean_queue({"nested": nested})


class NoDeletionRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Refusing redirect of scoped deletion/readback request")


class GardenDeletionHTTP:
    """Retain the public DELETE result that SyncHTTPClient.rm discards."""
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.opener = urllib.request.build_opener(NoDeletionRedirect())

    def _json(self, method: str, path: str, **params):
        request = urllib.request.Request(
            self.url + path + "?" + urlencode(params), method=method,
            headers={"Accept": "application/json", "X-OpenViking-Account": "default",
                     "X-OpenViking-User": "gwen", "X-OpenViking-Actor-Peer": "hermes"},
        )
        with self.opener.open(request, timeout=610) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"OpenViking deletion/readback HTTP {response.status}")
            try:
                return json.loads(response.read())
            except (ValueError, UnicodeError) as exc:
                raise RuntimeError("Malformed OpenViking deletion/readback response") from exc

    def delete(self, uri: str) -> dict:
        validate_delete_uri(uri)
        try:
            payload = self._json("DELETE", "/api/v1/fs", uri=uri, recursive="true", wait="true", timeout=600)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Deletion HTTP {exc.code}; semantic result unverified, recovery required") from exc
        result = payload.get("result") if isinstance(payload, dict) and payload.get("status") == "ok" else None
        if (not isinstance(result, dict) or result.get("uri") != uri
                or result.get("semantic_root_uri") != uri.rsplit("/", 1)[0]):
            raise RuntimeError("Malformed or out-of-scope deletion result; recovery required")
        if not isinstance(result.get("semantic_status"), str) or result["semantic_status"] not in {"complete", "completed"}:
            raise RuntimeError("Deletion semantic refresh is not complete; recovery required")
        require_clean_queue(result.get("queue_status"))
        # A fresh successful semantic result is required *before* checking absence.
        # DELETE 404 on a later retry cannot prove the parent's semantics were repaired.
        try:
            self._json("GET", "/api/v1/fs/stat", uri=uri)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return result
            raise RuntimeError("Deletion physical readback failed; recovery required") from exc
        raise RuntimeError("Deletion physical absence was not confirmed; recovery required")


def task_status(client, task_id: str) -> dict | None:
    if not hasattr(client, "get_task"):
        raise RuntimeError("OpenViking client does not expose the public task lookup API")
    return client.get_task(task_id)


def original_upload_finished(client, entry: dict) -> bool:
    """Do not lose an active/unknown upload when replacing its manifest entry."""
    if "task_id" not in entry and entry.get("status") not in {"accepted", "pending"}:
        return True
    entry.setdefault("task_id", None)  # Explicitly retain an unidentified acceptance.
    try:
        task = task_status(client, entry["task_id"]) if entry["task_id"] else None
    except Exception:
        task = None
    status = str(task.get("status") or "").lower() if isinstance(task, dict) else ""
    if status in {"completed", "complete", "success", "succeeded", "done", "failed", "error", "cancelled"}:
        entry.pop("task_id")
        return True
    entry.update(status="failed", failure="original upload has no verified terminal state; mutation held")
    return False


def checked_readback_child_uri(resource_uri: str, child_uri: object) -> str:
    relative = relative_for_uri(resource_uri)
    if not isinstance(child_uri, str) or not child_uri.startswith(resource_uri + "/"):
        raise ValueError("Readback child is outside its resource")
    parts = [unquote(part, errors="strict") for part in child_uri[len(resource_uri) + 1:].split("/")]
    if any("/" in part for part in parts):
        raise ValueError("Readback child contains an encoded separator")
    suffix = "/".join(parts)
    canonical = uri_for(relative + "/" + suffix)
    if child_uri not in {canonical, resource_uri + "/" + suffix}:
        raise ValueError("Readback child has a noncanonical path")
    # The SDK stores parser-generated Unicode names literally. Validate their
    # path without changing the exact URI returned by the resource listing.
    return child_uri


def remote_bytes(client, uri: str, *, resource_uri: str | None = None) -> bytes | None:
    if resource_uri is None:
        relative_for_uri(uri)
    else:
        checked_readback_child_uri(resource_uri, uri)
    try:
        value = client.download_bytes(uri)
    except Exception:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, dict):
        for key in ("content", "text", "data"):
            content = value.get(key)
            if isinstance(content, str):
                return content.encode("utf-8")
            if isinstance(content, bytes):
                return content
    return None


def remote_resource_bytes(client, uri: str, source_name: str) -> bytes | None:
    """Read one uploaded file whether the target is a file or resource tree."""
    direct = remote_bytes(client, uri)
    if direct is not None:
        return direct
    try:
        entries = client.ls(uri, recursive=True, output="original")
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    matches, file_entries = [], []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("isDir"), bool):
            return None
        try:
            child_uri = checked_readback_child_uri(uri, entry.get("uri"))
        except (ValueError, UnicodeError):
            return None
        if entry["isDir"]:
            continue
        file_entries.append(child_uri)
        name = entry.get("name") or unquote(child_uri.rsplit("/", 1)[-1])
        if name == source_name:
            matches.append(child_uri)
    if not matches and len(file_entries) == 1:
        matches = file_entries
    if len(matches) != 1:
        return None
    return remote_bytes(client, matches[0], resource_uri=uri)


def canonical_markdown_bytes(value: bytes) -> bytes:
    marker = b"---\n"
    if value.startswith(marker):
        end = value.find(b"\n---\n", len(marker))
        if end >= 0:
            return value[end + len(b"\n---\n") :]
    return value


def remote_content_matches(local: bytes, remote: bytes | None, *, text: bool) -> bool:
    if remote is None:
        return False
    if text:
        # OpenViking normalizes trailing whitespace on ingest; compare canonical
        # bodies modulo trailing whitespace so a lone trailing newline does not
        # force a perpetual re-upload.
        return canonical_markdown_bytes(local).rstrip() == canonical_markdown_bytes(remote).rstrip()
    return local == remote


def remote_resource_is_parsed_tree(client, uri: str) -> bool:
    """Detect a source file that OpenViking materialized as a parsed directory."""
    try:
        result = client.stat(uri)
    except Exception:
        return False
    return isinstance(result, dict) and result.get("isDir") is True


def remote_parsed_tree_bytes(client, uri: str) -> bytes | None:
    """Read the single parsed document child, failing closed on ambiguity."""
    try:
        entries = client.ls(uri, recursive=True, output="original")
    except Exception:
        return None
    if not isinstance(entries, list) or not entries:
        return None
    contents: list[bytes] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("isDir"), bool):
            return None
        try:
            child_uri = checked_readback_child_uri(uri, entry.get("uri"))
        except (ValueError, UnicodeError):
            return None
        if entry["isDir"]:
            continue
        content = remote_bytes(client, child_uri, resource_uri=uri)
        if content is None:
            return None
        contents.append(content)
    return contents[0] if len(contents) == 1 else None


def parsed_html_matches(local_html: bytes, parsed_content: bytes) -> bool:
    """Reproduce OpenViking's HTML conversion and require exact readback."""
    try:
        local_text = local_html.decode("utf-8")
    except UnicodeError:
        return False
    try:
        expected = OpenVikingHTMLParser()._html_to_markdown(local_text, base_url="")
    except Exception:
        return False
    return bool(expected) and expected.encode("utf-8") == parsed_content


def verified_content(client, relative: str, entry: dict, read_local) -> bool:
    """Bind remote readback to the scanned bytes, checking again after network IO."""
    expected = read_local(relative)
    if hash_bytes(expected) != entry["sha256"]:
        raise ValueError("local source changed while operation was pending")
    suffix = Path(relative).suffix.lower()
    actual = remote_bytes(client, entry["uri"])
    if actual is not None:
        matches = (remote_content_matches(expected, actual, text=True)
                   if suffix == ".md" else expected == actual)
    elif suffix == ".html":
        if remote_resource_is_parsed_tree(client, entry["uri"]):
            parsed = remote_parsed_tree_bytes(client, entry["uri"])
            matches = parsed is not None and parsed_html_matches(expected, parsed)
        else:
            matches = False
    else:
        tree_copy = remote_resource_bytes(client, entry["uri"], Path(relative).name)
        matches = (remote_content_matches(expected, tree_copy, text=True)
                   if suffix == ".md" else tree_copy is not None and expected == tree_copy)
    if not matches:
        return False
    if hash_bytes(read_local(relative)) != entry["sha256"]:
        raise ValueError("local source changed during remote readback")
    return True


def paths_overlap(left: str, right: str) -> bool:
    a, b = relative_parts(left), relative_parts(right)
    return a[:len(b)] == b or b[:len(a)] == a


def local_path_occupied(relative: str) -> bool:
    """Only ENOENT means absent; symlinks/ancestor files also occupy the scope."""
    parts = relative_parts(relative)
    cursor = GARDEN_ROOT
    if not stat.S_ISDIR(cursor.lstat().st_mode):
        raise ValueError("Garden root is not a real directory")
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            return False
        if index == len(parts) - 1 or not stat.S_ISDIR(mode):
            return True
    return False


def cleanup_occupied(source: str, owner: str, files: dict, current: dict) -> bool:
    for entries in (current, {path: entry for path, entry in files.items() if path != owner}):
        for relative, entry in entries.items():
            if entry["uri"] != uri_for(relative):
                raise ValueError("Resource URI does not match its occupied manifest/scan path")
            if paths_overlap(source, relative):
                return True
    return local_path_occupied(source)


def release_cleanup(entry: dict, uri: str) -> None:
    entry["cleanup_uris"] = [target for target in entry.get("cleanup_uris", []) if target != uri]
    for key in ("cleanup_sources", "cleanup_attempts"):
        if key in entry:
            entry[key].pop(uri, None)
            if not entry[key]:
                entry.pop(key)
    if not entry["cleanup_uris"]:
        entry.pop("cleanup_uris")


def mark_delete_pending(relative: str, entry: dict) -> None:
    validate_delete_uri(entry["uri"], expected=uri_for(relative))
    if not entry.get("delete_pending"):
        targets = [entry["uri"], *entry.get("cleanup_uris", [])]
        if entry.get("cleanup_uri"):
            targets.append(entry.pop("cleanup_uri"))
        entry["cleanup_uris"] = list(dict.fromkeys(targets))
        entry["cleanup_sources"] = {**entry.get("cleanup_sources", {}), entry["uri"]: relative}
    entry.update(delete_pending=True, status="failed", failure="deletion pending")


def cleanup_resources(deleter, relative: str, files: dict, current: dict, *, checkpoint, verify_destination=None) -> bool:
    """One guarded, checkpointed cleanup path for moves and deletion tombstones."""
    entry = files[relative]
    entry.update(status="failed", failure="cleanup pending")
    checkpoint(files)
    for uri in list(entry.get("cleanup_uris", [])):
        try:
            source = entry.get("cleanup_sources", {}).get(uri)
            if source is None:
                raise ValueError("cleanup source identity missing; recovery required")
            validate_delete_uri(uri, expected=uri_for(source),
                                destination=None if entry.get("delete_pending") and uri == entry["uri"] else relative)
            if cleanup_occupied(source, relative, files, current):
                release_cleanup(entry, uri)
                checkpoint(files)
                continue
            if uri in entry.get("cleanup_attempts", {}):
                raise RuntimeError(entry["cleanup_attempts"][uri])
            if deleter is None:
                raise RuntimeError("Garden deletion HTTP adapter required")
        except (OSError, ValueError, RuntimeError) as exc:
            entry["failure"] = str(exc)[:500]
            checkpoint(files)
            continue

        # Persist ambiguity before DELETE. A crash or semantic failure needs
        # explicit recovery, never a blind DELETE/404-as-success retry.
        entry.setdefault("cleanup_attempts", {})[uri] = "deletion result unverified; semantic recovery required"
        checkpoint(files)
        sent = False
        try:
            if verify_destination is not None and not verify_destination():
                raise ValueError("move destination differs before cleanup")
            # Recheck after checkpoint and network readback, immediately before DELETE.
            if not cleanup_occupied(source, relative, files, current):
                sent = True
                deleter.delete(uri)
            release_cleanup(entry, uri)
        except Exception as exc:
            entry["failure"] = str(exc)[:500]
            if sent:
                entry["cleanup_attempts"][uri] = entry["failure"] + "; recovery required"
            else:
                entry["cleanup_attempts"].pop(uri, None)
                if not entry["cleanup_attempts"]:
                    entry.pop("cleanup_attempts")
        checkpoint(files)
    if entry.get("cleanup_uris"):
        return False
    if entry.get("delete_pending"):
        files.pop(relative)
        checkpoint(files)
    return True


def reconcile_pending(client, files: dict, *, local_bytes=None, current=None, deleter=None, checkpoint=None) -> dict:
    """Advance accepted tasks only after terminal success and content readback."""
    report = {"completed": [], "pending": [], "failed": []}
    read_local = local_bytes or (lambda relative: checked_local_path(relative).read_bytes())
    save = checkpoint or (lambda value: None)
    if current is None and any(entry.get("cleanup_uris") or entry.get("delete_pending") for entry in files.values()):
        current = scan()
    for relative, entry in sorted(files.items()):
        entry_status = entry.get("status")
        cleanup_retry = entry.get("delete_pending") or entry.get("cleanup_attempts")
        if entry_status == "failed" and not cleanup_retry:
            report["failed"].append(relative)
            continue
        if entry_status in {"accepted", "pending"} or cleanup_retry and "task_id" in entry:
            task_id = entry.get("task_id")
            task = task_status(client, task_id) if task_id else None
            if not isinstance(task, dict):
                entry.setdefault("task_id", None)
                entry.update(status="failed", failure="OpenViking task not found; safe resubmission required")
                save(files)
                report["failed"].append(relative)
                continue
            status = str(task.get("status") or "").lower()
            if status in {"failed", "error", "cancelled"}:
                entry.pop("task_id", None)
                entry.update(status="failed", failure=str(task.get("error") or task.get("message") or status)[:500])
                save(files)
                report["failed"].append(relative)
                continue
            if status not in {"completed", "complete", "success", "succeeded", "done"}:
                entry["status"] = "pending"
                save(files)
                report["pending"].append(relative)
                continue
            entry.pop("task_id", None)
        elif entry_status != "completed" and not cleanup_retry:
            continue
        if entry.get("delete_pending"):
            resolved = cleanup_resources(deleter, relative, files, current or {}, checkpoint=save)
            report["completed" if resolved else "failed"].append(relative)
            continue
        cleanup_uris = entry.get("cleanup_uris", [])
        if entry_status == "completed" and not cleanup_uris:
            continue
        try:
            matches = verified_content(client, relative, entry, read_local)
        except FileNotFoundError:
            mark_delete_pending(relative, entry)
            save(files)
            report["failed"].append(relative)
            continue
        except (OSError, ValueError) as exc:
            entry.update(status="failed", failure=str(exc)[:500])
            save(files)
            report["failed"].append(relative)
            continue
        if not matches:
            entry["status"] = "failed"
            entry["failure"] = ("completed move remote content differs before cleanup" if entry_status == "completed"
                                else "terminal task succeeded but remote content differs")
            save(files)
            report["failed"].append(relative)
            continue
        if cleanup_uris:
            if not cleanup_resources(deleter, relative, files, current or {}, checkpoint=save,
                                     verify_destination=lambda: verified_content(client, relative, entry, read_local)):
                report["failed"].append(relative)
                continue
            try:
                if hash_bytes(read_local(relative)) != entry["sha256"]:
                    raise ValueError("local source changed during move cleanup")
            except (OSError, ValueError) as exc:
                entry.update(status="failed", failure=str(exc)[:500])
                save(files)
                report["failed"].append(relative)
                continue
        entry["status"] = "completed"
        entry.pop("failure", None)
        save(files)
        report["completed"].append(relative)
    return report


def checked_local_path(relative: str) -> Path:
    relative_parts(relative)
    path = GARDEN_ROOT / relative
    if has_scoped_symlink(path, GARDEN_ROOT):
        raise ValueError(f"Refusing symbolic-link upload: {relative}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(GARDEN_ROOT.resolve()) or not resolved.is_file():
        raise ValueError(f"Refusing out-of-scope upload: {relative}")
    return resolved


def submission_entry(client, relative: str, metadata: dict, *, wait: bool, cleanup_uris: list[str] | None = None, cleanup_sources: dict | None = None, cleanup_attempts: dict | None = None, accepted_callback=None, deleter=None) -> dict:
    if metadata["uri"] != uri_for(relative):
        raise ValueError("Upload URI does not match its expected source path")
    path = checked_local_path(relative)
    entry = {**metadata, "status": "accepted", "task_id": None}
    if cleanup_uris:
        entry["cleanup_uris"] = list(dict.fromkeys(cleanup_uris))
        if cleanup_sources:
            entry["cleanup_sources"] = {uri: cleanup_sources[uri] for uri in entry["cleanup_uris"] if uri in cleanup_sources}
        if cleanup_attempts:
            entry["cleanup_attempts"] = {uri: cleanup_attempts[uri] for uri in entry["cleanup_uris"] if uri in cleanup_attempts}
    # Persist unidentified intent before submission: an exception can hide acceptance.
    if accepted_callback:
        accepted_callback(entry)
    if Path(relative).suffix.lower() == ".md":
        # Refined wiki markdown is stored verbatim. add_resource would parse
        # and split long documents into a chunked tree, which exact readback
        # cannot verify; write the raw content instead. A legacy chunked tree
        # is replaced with a single file.
        if remote_resource_is_parsed_tree(client, metadata["uri"]):
            if deleter is None:
                entry.update(status="failed", failure="parsed resource tree needs a deleter to replace")
                return entry
            deleter.delete(metadata["uri"])
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError) as exc:
            entry.update(status="failed", failure=f"text upload is not readable UTF-8: {exc}")
            return entry
        response = client.write(metadata["uri"], content, mode="replace", wait=wait) or {}
        if not isinstance(response, dict):
            raise AttributeError("malformed write response")
        entry.pop("task_id", None)
        if wait and response.get("queue_status"):
            require_clean_queue(response["queue_status"])
        try:
            matches = verified_content(client, relative, metadata,
                                       lambda source: checked_local_path(source).read_bytes())
        except (OSError, ValueError) as exc:
            entry.update(status="failed", failure=str(exc)[:500])
            return entry
        if matches:
            entry.update({"status": "completed"})
            entry.pop("failure", None)
        else:
            entry.update({"status": "failed", "failure": "uploaded text content differs on readback"})
        return entry
    response = client.add_resource(
        str(path),
        to=metadata["uri"],
        wait=wait,
        timeout=600 if wait else None,
    ) or {}
    task_id = response.get("task_id")
    if task_id:
        entry.update({"status": "pending", "task_id": task_id})
    elif not wait:
        entry.update({"status": "failed", "task_id": None, "failure": "add response contained no task_id"})
    if accepted_callback:
        accepted_callback(entry)
    if wait:
        queue = response.get("queue_status") or client.wait_processed(timeout=600)
        require_clean_queue(queue)
        if not task_id:
            entry.pop("task_id", None)  # Synchronous processing proved the upload terminal.
        try:
            matches = verified_content(client, relative, metadata,
                                       lambda source: checked_local_path(source).read_bytes())
        except (OSError, ValueError) as exc:
            entry.update(status="failed", failure=str(exc)[:500])
            return entry
        if matches:
            entry.update({"status": "completed"})
            entry.pop("failure", None)
        else:
            entry.update({"status": "failed", "failure": "waited add completed but remote content differs"})
    return entry


def apply_changes(client: SyncHTTPClient, changes: dict, old: dict, new: dict, wait: bool, *, checkpoint=None, deleter=None) -> dict:
    files = copy.deepcopy(old)
    save = checkpoint or (lambda value: None)
    for source, destination in changes["move"]:
        if not original_upload_finished(client, files[source]):
            save(files)
            continue
        destination_uri = new[destination]["uri"]
        cleanup_uris = [
            uri for uri in [*old[source].get("cleanup_uris", []), old[source]["uri"]]
            if uri != destination_uri
        ]
        cleanup_sources = {**old[source].get("cleanup_sources", {}), old[source]["uri"]: source}
        files.pop(source, None)
        files[destination] = submission_entry(
            client,
            destination,
            new[destination],
            wait=wait,
            cleanup_uris=cleanup_uris,
            cleanup_sources=cleanup_sources,
            cleanup_attempts=old[source].get("cleanup_attempts"),
            accepted_callback=lambda entry, destination=destination: (files.__setitem__(destination, entry), save(files)),
            deleter=deleter,
        )
        save(files)
    for relative in changes["add"]:
        files[relative] = submission_entry(
            client, relative, new[relative], wait=wait,
            accepted_callback=lambda entry, relative=relative: (files.__setitem__(relative, entry), save(files)),
            deleter=deleter,
        )
        save(files)
    for relative in changes["modify"]:
        if not original_upload_finished(client, files.get(relative, {})):
            save(files)
            continue
        cleanup_uris = [uri for uri in files.get(relative, {}).get("cleanup_uris", []) if uri != new[relative]["uri"]]
        cleanup_sources = files.get(relative, {}).get("cleanup_sources")
        cleanup_attempts = files.get(relative, {}).get("cleanup_attempts")
        files[relative] = submission_entry(
            client, relative, new[relative], wait=wait,
            cleanup_uris=cleanup_uris,
            cleanup_sources=cleanup_sources,
            cleanup_attempts=cleanup_attempts,
            accepted_callback=lambda entry, relative=relative: (files.__setitem__(relative, entry), save(files)),
            deleter=deleter,
        )
        save(files)
    for relative in changes["delete"]:
        entry = files[relative]
        if not original_upload_finished(client, entry):
            save(files)
            continue
        mark_delete_pending(relative, entry)
        save(files)
        cleanup_resources(deleter, relative, files, new, checkpoint=save)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait", action="store_true", help="wait for all semantic processing; launchd normally enqueues asynchronously")
    parser.add_argument("--url", default=os.environ.get("OPENVIKING_ENDPOINT", "http://127.0.0.1:1933"))
    args = parser.parse_args()
    new = scan()
    if args.dry_run:
        old = load_manifest()["files"]
        changes = plan_changes(old, new)
        count = sum(len(items) for items in changes.values())
        report = {"changed": count, **changes}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    client = SyncHTTPClient(url=args.url, account="default", user="gwen")
    deleter = GardenDeletionHTTP(args.url)
    client.initialize()
    module = atomic_state_module()
    try:
        with module.json_transaction(MANIFEST_PATH, lambda: {"version": 2, "files": {}}) as manifest:
            manifest["version"] = 2
            files = manifest.setdefault("files", {})
            normalized = normalize_manifest({"version": manifest.get("version"), "files": files})
            manifest["files"] = files = normalized["files"]
            def checkpoint(current):
                module.atomic_write_json(MANIFEST_PATH, {
                    "version": 2, "synced_at": datetime.now(timezone.utc).isoformat(), "files": current,
                })
            reconciliation = reconcile_pending(client, files, current=new, deleter=deleter, checkpoint=checkpoint)
            changes = plan_changes(files, new)
            guarded = set(changes["modify"]) | set(changes["delete"])
            guarded.update(source for source, _ in changes["move"])
            guarded.update(path for path, entry in files.items()
                           if entry.get("status") == "failed" and "task_id" in entry)
            held = [path for path in sorted(guarded) if not original_upload_finished(client, files[path])]
            # The snapshot operation covers this batch; preserve it while an
            # original upload is unresolved, before any new snapshot write.
            changes = {kind: [] for kind in changes} if held else plan_changes(files, new)
            count = sum(len(items) for items in changes.values())
            report = {"changed": count, **changes, "reconciliation": reconciliation}
            if held:
                report["held"] = held
                checkpoint(files)
            elif count:
                operation = load_or_create_snapshot_operation(files, new)
                snapshot = commit_snapshot_safely(client, message=operation["message"])
                updated = apply_changes(
                    client,
                    changes,
                    files,
                    new,
                    wait=args.wait,
                    checkpoint=checkpoint,
                    deleter=deleter,
                )
                manifest["files"] = updated
                report["snapshot"] = snapshot
                report["reconciliation_after_submit"] = reconcile_pending(
                    client, updated, current=new, deleter=deleter, checkpoint=checkpoint,
                )
                clear_snapshot_operation(operation)
            elif not any(entry.get("status") in {"accepted", "pending", "failed"} for entry in files.values()):
                clear_snapshot_operation()
            manifest["synced_at"] = datetime.now(timezone.utc).isoformat()
    finally:
        client.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return sync_exit_code(manifest["files"])


if __name__ == "__main__":
    raise SystemExit(main())
