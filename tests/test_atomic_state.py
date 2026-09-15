from __future__ import annotations

import importlib.util
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/atomic_state.py"


def load_module():
    spec = importlib.util.spec_from_file_location("atomic_state", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def increment(path: str) -> None:
    module = load_module()
    with module.json_transaction(Path(path), lambda: {"count": 0}) as state:
        state["count"] += 1


class AtomicStateTests(unittest.TestCase):
    def test_transaction_serializes_read_modify_write_across_processes(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            processes = [multiprocessing.Process(target=increment, args=(str(path),)) for _ in range(20)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(5)
            self.assertTrue(all(process.exitcode == 0 for process in processes))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"count": 20})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_exception_does_not_publish_partial_state(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"value": "stable"}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "abort"):
                with module.json_transaction(path, dict) as state:
                    state["value"] = "partial"
                    raise RuntimeError("abort")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": "stable"})


if __name__ == "__main__":
    unittest.main()
