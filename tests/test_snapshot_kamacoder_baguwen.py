from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "automation/snapshot_kamacoder_baguwen.py"
SPEC = importlib.util.spec_from_file_location("snapshot_kamacoder_baguwen", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


def sitemap(entries: list[tuple[str, str]]) -> bytes:
    rows = "".join(
        f"<url><loc>{url}</loc><lastmod>{lastmod}</lastmod></url>"
        for url, lastmod in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{rows}</urlset>"
    ).encode()


class URLSecurityTests(unittest.TestCase):
    def test_sitemap_rejects_untrusted_or_noncanonical_selected_urls(self):
        attacks = (
            "http://notes.kamacoder.com/base/a.html",
            "https://evil.example/base/a.html",
            "https://user@notes.kamacoder.com/base/a.html",
            "https://notes.kamacoder.com:443/base/a.html",
            "https://notes.kamacoder.com/base/a.html?next=http://127.0.0.1/",
            "https://notes.kamacoder.com/base/a.html#fragment",
            "https://notes.kamacoder.com/base/../admin.html",
            "https://notes.kamacoder.com/base/%2e%2e/admin.html",
            "https://notes.kamacoder.com/base/%252e%252e/admin.html",
            "https://notes.kamacoder.com/base/a%2fb.html",
            "https://notes.kamacoder.com/base/a%252fb.html",
            "https://notes.kamacoder.com/base/a%5cb.html",
            "https://notes.kamacoder.com/base/a\\b.html",
        )
        for url in attacks:
            with self.subTest(url=url), self.assertRaises(ValueError):
                snapshot.parse_sitemap(sitemap([(url, "2026-01-01")]))

    def test_redirect_handler_rejects_redirect_before_following_it(self):
        handler = snapshot.StrictHTTPSRedirect("notes.kamacoder.com")
        for target in (
            "http://notes.kamacoder.com/base/a.html",
            "https://127.0.0.1/base/a.html",
            "https://notes.kamacoder.com:443/base/a.html",
            "https://notes.kamacoder.com/base/%2e%2e/admin.html",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, "Found", {}, target)

    def test_fetch_rejects_an_invalid_final_response_url(self):
        class Response:
            status = 200
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"body"

            def geturl(self):
                return "https://localhost/private"

        class Opener:
            def open(self, request, timeout):
                return Response()

        with patch.object(snapshot.urllib.request, "build_opener", return_value=Opener()):
            with self.assertRaises(ValueError):
                snapshot.fetch("https://notes.kamacoder.com/base/a.html")

    def test_resolved_target_must_stay_below_managed_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "managed"
            root.mkdir()
            self.assertEqual(
                snapshot.resolved_target(root, Path("notes.kamacoder.com/base/a.html")),
                (root / "notes.kamacoder.com/base/a.html").resolve(),
            )
            for relative in (Path("../escape"), Path("/tmp/escape")):
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    snapshot.resolved_target(root, relative)


class RefreshTests(unittest.TestCase):
    def test_install_rejects_symlinked_output_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            outside = root / "outside"
            outside.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(outside, target_is_directory=True)
            output = linked_parent / "snapshot"
            temporary_tree = root / "new-tree"
            temporary_tree.mkdir()
            (temporary_tree / "replacement.bin").write_bytes(b"replacement")
            wiki = root / "index.md"
            wiki.write_bytes(b"manual index\n")

            with self.assertRaises(ValueError):
                snapshot.install_tree_and_index(
                    output, temporary_tree, wiki, b"changed index\n",
                )

            self.assertFalse((outside / "snapshot").exists())
            self.assertEqual(wiki.read_bytes(), b"manual index\n")

    def test_install_rejects_symlinked_managed_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "actual"
            target.mkdir()
            sentinel = target / "sentinel.bin"
            sentinel.write_bytes(b"preserve exactly")
            output = root / "snapshot-link"
            output.symlink_to(target, target_is_directory=True)
            temporary_tree = root / "new-tree"
            temporary_tree.mkdir()
            (temporary_tree / "replacement.bin").write_bytes(b"replacement")
            wiki = root / "index.md"
            wiki.write_bytes(b"manual index\n")

            with self.assertRaises(ValueError):
                snapshot.install_tree_and_index(
                    output, temporary_tree, wiki, b"changed index\n",
                )

            self.assertTrue(output.is_symlink())
            self.assertEqual(sentinel.read_bytes(), b"preserve exactly")
            self.assertEqual(wiki.read_bytes(), b"manual index\n")

    def test_refresh_replaces_complete_tree_prunes_stale_and_updates_generated_index(self):
        selected = [
            ("https://notes.kamacoder.com/base/a.html", "2026-01-02T03:04:05Z"),
            ("https://notes.kamacoder.com/interview/llm/b.html", "2026-02-03T04:05:06Z"),
        ]
        raw_sitemap = sitemap(selected)
        payloads = {
            snapshot.SITEMAP_URL: (raw_sitemap, "application/xml"),
            snapshot.ROBOTS_URL: (b"User-agent: *\nAllow: /\n", "text/plain"),
            snapshot.ANNOUNCEMENT_URL: (b"<html><title>Release</title><body>release body</body></html>\n", "text/html"),
            selected[0][0]: (b"<html><title>Base A</title><body>base body</body></html>\n\n", "text/html"),
            selected[1][0]: (b"<html><title>LLM B</title><body>llm body</body></html>", "text/html"),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "snapshot"
            stale = output / "notes.kamacoder.com/base/stale.html"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"stale bytes")
            wiki = root / "index.md"
            wiki.write_text(
                "manual policy before\n\n"
                f"{snapshot.GENERATED_BEGIN}\nold generated text\n{snapshot.GENERATED_END}\n\n"
                "manual policy after\n",
                encoding="utf-8",
            )

            def fake_fetch(url: str):
                return payloads[url]

            stdout = io.StringIO()
            with patch.object(snapshot, "fetch", side_effect=fake_fetch), \
                    patch.object(sys, "argv", [
                        "snapshot_kamacoder_baguwen.py", "--output", str(output),
                        "--wiki-index", str(wiki),
                    ]), patch("sys.stdout", stdout):
                self.assertEqual(snapshot.main(), 0)

            self.assertFalse(stale.exists())
            expected_files = {snapshot.relative_path(url).as_posix() for url in payloads}
            actual_files = {
                path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()
            }
            self.assertEqual(actual_files, expected_files)
            for url, (data, _) in payloads.items():
                self.assertEqual((output / snapshot.relative_path(url)).read_bytes(), data)

            text = wiki.read_text(encoding="utf-8")
            self.assertIn("manual policy before", text)
            self.assertIn("manual policy after", text)
            self.assertEqual(text.count(snapshot.GENERATED_BEGIN), 1)
            self.assertEqual(text.count(snapshot.GENERATED_END), 1)
            self.assertIn("计算机基础：1 个页面", text)
            self.assertIn("大模型面经：1 个页面", text)
            self.assertIn("2026-02-03T04:05:06Z", text)
            for url in [snapshot.ANNOUNCEMENT_URL, *(url for url, _ in selected)]:
                self.assertIn(url, text)
                self.assertIn(snapshot.relative_path(url).as_posix(), text)

            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["files_written"], len(payloads))
            self.assertEqual(summary["html_pages"], 3)
            self.assertRegex(summary["snapshot_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn(summary["snapshot_sha256"], text)

    def test_refresh_failure_keeps_existing_tree_and_index_unchanged(self):
        raw_sitemap = sitemap([
            ("https://notes.kamacoder.com/base/a.html", "2026-01-01"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "snapshot"
            output.mkdir()
            existing = output / "keep.bin"
            existing.write_bytes(b"keep exactly")
            wiki = root / "index.md"
            original_index = (
                f"manual\n{snapshot.GENERATED_BEGIN}\nold\n{snapshot.GENERATED_END}\n"
            ).encode()
            wiki.write_bytes(original_index)

            def failing_fetch(url: str):
                if url == snapshot.SITEMAP_URL:
                    return raw_sitemap, "application/xml"
                raise RuntimeError("fixture download failed")

            with patch.object(snapshot, "fetch", side_effect=failing_fetch), \
                    patch.object(sys, "argv", [
                        "snapshot_kamacoder_baguwen.py", "--output", str(output),
                        "--wiki-index", str(wiki),
                    ]), self.assertRaises(RuntimeError):
                snapshot.main()

            self.assertEqual(existing.read_bytes(), b"keep exactly")
            self.assertEqual(wiki.read_bytes(), original_index)


if __name__ == "__main__":
    unittest.main()
