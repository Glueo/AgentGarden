#!/usr/bin/env python3
"""Small human-readable health check for the local Agent Garden."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import stat
import urllib.parse
import urllib.request
from pathlib import Path


IDENTITY_HEADERS = {
    "Accept": "application/json",
    "X-OpenViking-Account": "default",
    "X-OpenViking-User": "gwen",
    "X-OpenViking-Actor-Peer": "hermes",
}
ARCHIVE_NODE_LIMIT = 1000
# The pinned sessions endpoint inherits VikingFS.ls's default node limit.
SESSION_LIST_LIMIT = 1000


def http_json(url: str, **params) -> tuple[bool, object]:
    try:
        target = url + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(target, headers=IDENTITY_HEADERS)
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return 200 <= response.status < 300, json.loads(raw) if raw else {"status": response.status}
    except Exception as exc:
        return False, str(exc)


def summarize_tasks(tasks: list[dict], *, limit: int | None = None) -> dict:
    latest: dict[tuple[str, str], dict] = {}
    historical_failures = 0
    pending = []
    for index, task in enumerate(list_items(tasks, required_fields=("task_id", "task_type", "status"))):
        updated_at = task.get("updated_at")
        if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)) or not math.isfinite(updated_at):
            raise ValueError(f"task item {index} requires a finite numeric updated_at")
        if task.get("resource_id") is not None and not isinstance(task["resource_id"], str):
            raise ValueError(f"task item {index} requires a string or null resource_id")
        status = str(task.get("status") or "").lower()
        safe = {
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "resource_id": task.get("resource_id"),
            "status": task.get("status"),
        }
        if status in {"failed", "error"}:
            historical_failures += 1
        elif status not in {"completed", "complete", "success", "succeeded", "done"}:
            pending.append(safe)
        key = (task["task_type"], task.get("resource_id") or task["task_id"])
        if key not in latest or updated_at >= latest[key]["updated_at"]:
            latest[key] = task
    failed = []
    for task in latest.values():
        safe = {
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "resource_id": task.get("resource_id"),
            "status": task.get("status"),
        }
        status = str(task.get("status") or "").lower()
        if status in {"failed", "error"}:
            failed.append(safe)
    return {
        "historical_failures": historical_failures,
        "unresolved_failed": sorted(failed, key=lambda item: str(item["task_id"])),
        "pending": sorted(pending, key=lambda item: str(item["task_id"])),
        "enumeration_errors": ["task_limit_reached"] if limit is not None and len(tasks) >= limit else [],
    }


def summarize_sync_manifest(files: dict) -> dict:
    pending = []
    failed = []
    for path, entry in sorted(files.items()):
        status = entry.get("status", "unverified")
        if status in {"accepted", "pending"}:
            pending.append({"path": path, "task_id": entry.get("task_id")})
        elif status != "completed":
            failed.append({
                "path": path,
                "task_id": entry.get("task_id"),
                "reason": entry.get("failure") or f"unverified sync status: {status}",
            })
        elif any(entry.get(field) for field in ("cleanup_uris", "cleanup_uri", "delete_pending")):
            pending.append({"path": path, "task_id": entry.get("task_id")})
    return {"pending": pending, "failed": failed}


def validate_sync_manifest(payload: object) -> dict:
    """Validate a copy using the synchronizer's canonical schema."""
    if not isinstance(payload, dict):
        raise ValueError("sync manifest must be an object")
    if not isinstance(payload.get("files"), dict):
        raise ValueError("sync manifest files must be a mapping")
    spec = importlib.util.spec_from_file_location("garden_sync_schema", Path(__file__).with_name("sync_garden.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module.normalize_manifest(copy.deepcopy(payload))["files"]
    except (ImportError, TypeError, AttributeError) as exc:
        raise ValueError("sync manifest schema is invalid or unavailable") from exc


def unwrap_result(payload: object) -> object:
    return payload.get("result", payload) if isinstance(payload, dict) else payload


def list_items(payload: object, *, required_fields: tuple[str, ...] = ()) -> list[dict]:
    value = unwrap_result(payload)
    if isinstance(value, dict):
        for key in ("entries", "items", "files", "sessions"):
            if isinstance(value.get(key), list):
                value = value[key]
                break
    if not isinstance(value, list):
        raise ValueError("unrecognized listing response shape")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("listing response contains a non-object item")
        for field in required_fields:
            text = item.get(field)
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"listing item {index} requires a non-empty string {field}")
    return value


def archive_items(payload: object) -> list[dict]:
    entries = list_items(payload, required_fields=("name", "uri"))
    for index, entry in enumerate(entries):
        name, uri = entry["name"], entry["uri"]
        if name in {".done", ".failed.json"} and not uri.endswith("/" + name):
            raise ValueError(f"archive item {index} marker name does not match its URI")
    return entries


def summarize_archive_markers(entries: list[dict], failed_payloads: dict[str, dict] | None = None) -> dict:
    failed_payloads = failed_payloads or {}
    archives: dict[str, dict[str, str]] = {}
    for entry in archive_items(entries):
        name, uri = entry["name"], entry["uri"]
        if name not in {".done", ".failed.json"}:
            continue
        archives.setdefault(uri.removesuffix("/" + name), {})[name] = uri
    unresolved = []
    completed = 0
    for archive_uri, markers in sorted(archives.items()):
        if ".done" in markers:
            completed += 1
            continue
        if ".failed.json" not in markers:
            continue
        payload = failed_payloads.get(markers[".failed.json"], {})
        item: dict[str, object] = {"archive_uri": archive_uri}
        if payload.get("stage"):
            item["stage"] = payload["stage"]
        if isinstance(payload.get("blocked_by"), list):
            item["blocked_by"] = [str(value) for value in payload["blocked_by"][:20]]
        unresolved.append(item)
    return {"completed": completed, "unresolved_failed": unresolved}


def persistent_archive_health(base_url: str, sessions_payload: object) -> dict:
    entries = []
    failed_payloads = {}
    errors = []
    try:
        sessions = list_items(sessions_payload, required_fields=("session_id", "uri"))
    except ValueError as exc:
        return {"completed": 0, "unresolved_failed": [], "enumeration_errors": [f"invalid_sessions:{exc}"]}
    if len(sessions) >= SESSION_LIST_LIMIT:
        return {"completed": 0, "unresolved_failed": [], "enumeration_errors": ["session_limit_reached"]}
    for session in sessions:
        uri = session["uri"]
        ok, listing = http_json(
            base_url + "/api/v1/fs/ls",
            uri=uri + "/history",
            recursive="true",
            output="original",
            show_all_hidden="true",
            node_limit=ARCHIVE_NODE_LIMIT,
        )
        if not ok:
            errors.append(str(session.get("session_id") or uri))
            continue
        try:
            session_entries = archive_items(listing)
        except ValueError as exc:
            errors.append(f"{session.get('session_id') or uri}:{exc}")
            continue
        if len(session_entries) >= ARCHIVE_NODE_LIMIT:
            errors.append(f"{session.get('session_id') or uri}:node_limit_reached")
        entries.extend(session_entries)
        for entry in session_entries:
            marker_uri = str(entry.get("uri") or "")
            if entry.get("name") != ".failed.json" or not marker_uri:
                continue
            read_ok, payload = http_json(
                base_url + "/api/v1/content/read",
                uri=marker_uri,
                offset=0,
                limit=-1,
                raw="true",
            )
            value = unwrap_result(payload)
            if read_ok:
                if isinstance(value, dict) and isinstance(value.get("content"), str):
                    try:
                        value = json.loads(value["content"])
                    except json.JSONDecodeError:
                        value = {}
                elif isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        value = {}
                if isinstance(value, dict):
                    failed_payloads[marker_uri] = value
    report = summarize_archive_markers(entries, failed_payloads)
    report["enumeration_errors"] = errors
    return report


def unwrap_tasks(payload: object) -> list[dict]:
    if isinstance(payload, list):
        if not all(isinstance(item, dict) for item in payload):
            raise ValueError("task response contains a non-object item")
        return payload
    if isinstance(payload, dict):
        if "result" not in payload and "tasks" not in payload:
            raise ValueError("unrecognized task response shape")
        value = payload.get("result", payload.get("tasks"))
        if isinstance(value, dict):
            if "tasks" in value:
                value = value["tasks"]
            elif "items" in value:
                value = value["items"]
            else:
                raise ValueError("unrecognized nested task response shape")
        if isinstance(value, list):
            if not all(isinstance(item, dict) for item in value):
                raise ValueError("task response contains a non-object item")
            return value
    raise ValueError("unrecognized task response shape")


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    checks = {}
    checks["project"] = project.is_dir()
    checks["garden"] = (project / "garden/_system/policy.md").is_file()
    config = Path.home() / ".openviking/ov.conf"
    checks["openviking_config_0600"] = config.is_file() and stat.S_IMODE(config.stat().st_mode) == 0o600
    base_url = "http://127.0.0.1:1933"
    ready, details = http_json(base_url + "/ready")
    checks["openviking_configured"] = config.is_file()
    checks["openviking_available"] = ready
    checks["ready_details"] = details
    checks["hermes_config"] = (Path.home() / ".hermes/config.yaml").is_file()
    checks["runtime_writable"] = os.access(project / ".runtime", os.W_OK)
    tasks_ok, task_payload = http_json(base_url + "/api/v1/tasks", limit=200)
    try:
        task_report = summarize_tasks(unwrap_tasks(task_payload), limit=200) if tasks_ok else {"historical_failures": 0, "unresolved_failed": [], "pending": [], "enumeration_errors": [str(task_payload)]}
    except ValueError as exc:
        task_report = {"historical_failures": 0, "unresolved_failed": [], "pending": [], "enumeration_errors": [str(exc)]}
    manifest_path = project / ".runtime/sync-manifest.json"
    try:
        manifest_files = validate_sync_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
        sync_report = {**summarize_sync_manifest(manifest_files), "enumeration_errors": []}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        sync_report = {"pending": [], "failed": [], "enumeration_errors": [f"invalid_sync_manifest:{exc}"]}
    sessions_ok, sessions_payload = http_json(base_url + "/api/v1/sessions")
    archive_report = persistent_archive_health(base_url, sessions_payload) if sessions_ok else {"completed": 0, "unresolved_failed": [], "enumeration_errors": ["sessions_unavailable"]}
    checks["semantic_tasks"] = task_report
    checks["semantic_archives"] = archive_report
    checks["garden_sync"] = sync_report
    checks["semantic_healthy"] = bool(
        tasks_ok
        and not task_report["enumeration_errors"]
        and not task_report["unresolved_failed"]
        and not task_report["pending"]
        and not archive_report["unresolved_failed"]
        and not archive_report["enumeration_errors"]
        and not sync_report["failed"]
        and not sync_report["pending"]
        and not sync_report["enumeration_errors"]
    )
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    boolean_checks = [value for value in checks.values() if isinstance(value, bool)]
    return 0 if all(boolean_checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
