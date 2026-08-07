#!/usr/bin/env python3
"""One-way, idempotent Garden to OpenViking synchronizer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from openviking import SyncHTTPClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GARDEN_ROOT = PROJECT_ROOT / "garden"
MANIFEST_PATH = PROJECT_ROOT / ".runtime/sync-manifest.json"
SYNC_ROOTS = ("wiki", "sources", "skills")
BASE_URI = os.environ.get("AGENT_GARDEN_VIKING_ROOT", "viking://user/gwen/resources/garden")
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv", ".sh", ".zsh", ".js", ".ts", ".html", ".css"}


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
    if args.dry_run or count == 0:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    client = SyncHTTPClient(url=args.url, account="default", user="gwen", actor_peer_id="hermes")
    client.initialize()
    try:
        snapshot = client.snapshot.commit(message=f"before garden sync {datetime.now(timezone.utc).isoformat()}", author_name="Agent Garden", author_email="agent-garden@localhost")
        apply_changes(client, changes, old, new, wait=args.wait)
        # The mutations have been accepted at this point. Persist their hashes before
        # waiting for semantic enrichment so a slow VLM task cannot cause a duplicate
        # submission on the next tick.
        save_manifest(new)
        if args.wait:
            client.wait_processed(timeout=600)
        report["snapshot"] = snapshot
    finally:
        client.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
