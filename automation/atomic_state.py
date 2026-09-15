#!/usr/bin/env python3
"""Small cross-process transactions for JSON runtime state."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


def load_json(path: Path, default_factory: Callable[[], dict]) -> dict:
    if not path.exists():
        return default_factory()
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def json_transaction(path: Path, default_factory: Callable[[], dict]) -> Iterator[dict]:
    """Hold an exclusive flock across one load-modify-save transaction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = load_json(path, default_factory)
        try:
            yield state
        except BaseException:
            raise
        else:
            atomic_write_json(path, state)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
