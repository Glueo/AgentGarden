#!/usr/bin/env python3
"""One-way, idempotent Garden to OpenViking synchronizer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from openviking import SyncHTTPClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GARDEN_ROOT = PROJECT_ROOT / "garden"
MANIFEST_PATH = PROJECT_ROOT / ".runtime/sync-manifest.json"
PENDING_SNAPSHOT_PATH = PROJECT_ROOT / ".runtime/sync-snapshot-pending.json"
SYNC_ROOTS = ("wiki", "sources")
BASE_URI = os.environ.get("AGENT_GARDEN_VIKING_ROOT", "viking://user/gwen/resources/garden")
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv", ".sh", ".zsh", ".js", ".ts", ".html", ".css"}
SNAPSHOT_AMBIGUOUS_STATUS = (502, 503, 504)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def uri_for(relative: str) -> str:
    encoded = "/".join(quote(part, safe="._-~") for part in Path(relative).parts)
    return f"{BASE_URI}/{encoded}"


def scan() -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for root_name in SYNC_ROOTS:
        root = GARDEN_ROOT / root_name
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith(".") or ".obsidian" in path.parts or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(GARDEN_ROOT).as_posix()
            entries[relative] = {
                "sha256": digest(path),
                "uri": uri_for(relative),
                "text": path.suffix.lower() in TEXT_SUFFIXES,
            }
    return entries


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "files": {}}
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "files": data.get("files", {})}


def save_manifest(files: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST_PATH.with_suffix(".tmp")
    payload = {"version": 1, "synced_at": datetime.now(timezone.utc).isoformat(), "files": files}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, MANIFEST_PATH)


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
    removed = old_paths - new_paths
    added = new_paths - old_paths
    modified = {path for path in old_paths & new_paths if old[path]["sha256"] != new[path]["sha256"]}
    moves = []
    by_hash: dict[str, list[str]] = {}
    for path in removed:
        by_hash.setdefault(old[path]["sha256"], []).append(path)
    for destination in list(added):
        matches = by_hash.get(new[destination]["sha256"], [])
        if len(matches) == 1:
            source = matches[0]
            moves.append((source, destination))
            removed.remove(source)
            added.remove(destination)
            by_hash.pop(new[destination]["sha256"], None)
    return {"add": sorted(added), "modify": sorted(modified), "move": sorted(moves), "delete": sorted(removed)}


def apply_changes(client: SyncHTTPClient, changes: dict, old: dict, new: dict, wait: bool) -> None:
    for source, destination in changes["move"]:
        client.mv(old[source]["uri"], new[destination]["uri"])
    for relative in changes["add"]:
        client.add_resource(str(GARDEN_ROOT / relative), to=new[relative]["uri"], wait=wait, timeout=600 if wait else None)
    for relative in changes["modify"]:
        path = GARDEN_ROOT / relative
        # add_resource owns a resource subtree even for one local file. Calling
        # it again with the same exact target is OpenViking's incremental
        # replace path and refreshes parsed content, summaries, and vectors.
        client.add_resource(str(path), to=new[relative]["uri"], wait=wait, timeout=600 if wait else None)
    for relative in changes["delete"]:
        # add_resource represents even one local file as a resource subtree.
        # The URI is exact and manifest-owned, so recursive deletion is scoped to that one resource.
        client.rm(old[relative]["uri"], recursive=True, wait=wait, timeout=600 if wait else None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait", action="store_true", help="wait for all semantic processing; launchd normally enqueues asynchronously")
    parser.add_argument("--url", default=os.environ.get("OPENVIKING_ENDPOINT", "http://127.0.0.1:1933"))
    args = parser.parse_args()
    old = load_manifest()["files"]
    new = scan()
    changes = plan_changes(old, new)
    count = sum(len(items) for items in changes.values())
    report = {"changed": count, **changes}
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if count == 0:
        clear_snapshot_operation()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    client = SyncHTTPClient(url=args.url, account="default", user="gwen", actor_peer_id="hermes")
    client.initialize()
    operation = load_or_create_snapshot_operation(old, new)
    try:
        snapshot = commit_snapshot_safely(client, message=operation["message"])
        apply_changes(client, changes, old, new, wait=args.wait)
        # The mutations have been accepted at this point. Persist their hashes before
        # waiting for semantic enrichment so a slow VLM task cannot cause a duplicate
        # submission on the next tick.
        save_manifest(new)
        clear_snapshot_operation(operation)
        if args.wait:
            client.wait_processed(timeout=600)
        report["snapshot"] = snapshot
    finally:
        client.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
