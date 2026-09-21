#!/usr/bin/env python3
"""Snapshot the Agent-internship-relevant Kamacoder v7 pages."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

SITEMAP_URL = "https://notes.kamacoder.com/sitemap.xml"
ROBOTS_URL = "https://notes.kamacoder.com/robots.txt"
ANNOUNCEMENT_URL = "https://programmercarl.com/other/kstar_baguwen.html"
PREFIXES = ("/base/", "/interview/llm/")
ALLOWED_HOSTS = frozenset({"notes.kamacoder.com", "programmercarl.com"})
USER_AGENT = "Mozilla/5.0 (compatible; AgentGardenSnapshot/1.0; personal-study-archive)"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "garden/resources/kamacoder-baguwen-v7"
DEFAULT_WIKI_INDEX = PROJECT_ROOT / "garden/wiki/卡码笔记第七版八股文资源.md"
GENERATED_BEGIN = "<!-- BEGIN GENERATED KAMACODER SNAPSHOT -->"
GENERATED_END = "<!-- END GENERATED KAMACODER SNAPSHOT -->"
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def validate_url(url: str, expected_host: str) -> urllib.parse.SplitResult:
    """Accept one canonical HTTPS URL on exactly the expected origin."""
    if not isinstance(url, str) or not url:
        raise ValueError("URL must be a non-empty string")
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"invalid URL: {url!r}") from exc
    if (parts.scheme != "https" or parts.hostname != expected_host or parts.netloc != expected_host
            or parts.username is not None or parts.password is not None or port is not None
            or parts.query or parts.fragment):
        raise ValueError(f"refusing URL outside canonical HTTPS origin: {url!r}")
    if not parts.path.startswith("/") or "\\" in parts.path:
        raise ValueError(f"refusing noncanonical URL path: {url!r}")
    if re.search(r"%(?![0-9A-Fa-f]{2})", parts.path):
        raise ValueError(f"refusing malformed percent escape: {url!r}")

    decoded = parts.path
    for _ in range(8):
        next_value = urllib.parse.unquote(decoded, errors="strict")
        if next_value == decoded:
            break
        if next_value.count("/") != decoded.count("/") or "\\" in next_value:
            raise ValueError(f"refusing encoded path separator: {url!r}")
        decoded = next_value
    else:
        raise ValueError(f"refusing excessively encoded URL path: {url!r}")
    if _PERCENT_ESCAPE.search(decoded):
        raise ValueError(f"refusing recursively encoded URL path: {url!r}")
    segments = decoded.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError(f"refusing dot path segment: {url!r}")
    if any(segment == "" for segment in segments[1:-1]):
        raise ValueError(f"refusing empty path segment: {url!r}")
    return parts


def expected_host(url: str) -> str:
    try:
        host = urllib.parse.urlsplit(url).hostname
    except ValueError as exc:
        raise ValueError(f"invalid URL: {url!r}") from exc
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"refusing unexpected snapshot host: {url!r}")
    return host


class StrictHTTPSRedirect(urllib.request.HTTPRedirectHandler):
    """Validate every redirect target before urllib sends the next request."""

    def __init__(self, expected_host: str):
        super().__init__()
        self.expected_host = expected_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.expected_host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> tuple[bytes, str]:
    host = expected_host(url)
    validate_url(url, host)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        },
    )
    opener = urllib.request.build_opener(StrictHTTPSRedirect(host))
    with opener.open(request, timeout=45) as response:
        final_url = response.geturl()
        validate_url(final_url, host)
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return response.read(), response.headers.get("Content-Type", "")


def parse_sitemap(raw: bytes) -> tuple[list[str], dict[str, str]]:
    root = ET.fromstring(raw)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: list[str] = []
    lastmods: dict[str, str] = {}
    for entry in root.findall("s:url", namespace):
        loc = entry.findtext("s:loc", namespaces=namespace)
        if not loc:
            continue
        parts = validate_url(loc, "notes.kamacoder.com")
        if parts.path.startswith(PREFIXES):
            urls.append(loc)
            lastmods[loc] = entry.findtext("s:lastmod", default="", namespaces=namespace)
    return sorted(set(urls)), lastmods


def relative_path(url: str) -> Path:
    host = expected_host(url)
    parts = validate_url(url, host)
    path = urllib.parse.unquote(parts.path, errors="strict")
    if path.endswith("/"):
        path += "index.html"
    relative = Path(host, *path.lstrip("/").split("/"))
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"refusing unsafe snapshot path for {url!r}")
    return relative


def resolved_target(root: Path, relative: Path) -> Path:
    """Resolve a proposed file target and prove it remains below the managed root."""
    if relative.is_absolute():
        raise ValueError("snapshot target must be relative")
    root_resolved = root.resolve(strict=True)
    target = (root / relative).resolve(strict=False)
    if target == root_resolved or not target.is_relative_to(root_resolved):
        raise ValueError("snapshot target escapes managed output")
    return target


def has_symlink_component(path: Path) -> bool:
    """Check the literal absolute path before resolving any component."""
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            return True
    return False


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot_digest(payloads: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for url in sorted(payloads):
        digest.update(url.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payloads[url])
    return digest.hexdigest()


def html_title(raw: bytes, url: str) -> str:
    parser = _TitleParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    title = " ".join(" ".join(parser.parts).split()).replace("|", "-")
    return title or Path(urllib.parse.urlsplit(url).path).name or url


def generated_region(
    selected: list[str], lastmods: dict[str, str], payloads: dict[str, bytes], digest: str
) -> str:
    counts = {
        prefix: sum(urllib.parse.urlsplit(url).path.startswith(prefix) for url in selected)
        for prefix in PREFIXES
    }
    latest = max(lastmods.values())
    page_urls = [ANNOUNCEMENT_URL, *selected]
    lines = [
        GENERATED_BEGIN,
        "## 自动生成快照清单",
        "",
        "以下统计与索引由 `python3 automation/snapshot_kamacoder_baguwen.py` 确定性更新；请勿手工编辑此区域。",
        "",
        "- 第七版发布说明：1 个页面；",
        f"- 计算机基础：{counts['/base/']} 个页面；",
        f"- 大模型面经：{counts['/interview/llm/']} 个页面；",
        "- 抓取元数据：原始 `robots.txt` 与 `sitemap.xml`；",
        f"- 共 {len(page_urls)} 个原始 HTML 页面、2 个原始元数据文件；",
        f"- sitemap 中选定页面的最新修改时间：`{latest}`；",
        "- 按 URL 与原始响应字节计算的快照集合 SHA-256：",
        "",
        f"`{digest}`",
        "",
        "### 完整本地页面索引",
        "",
    ]
    for url in page_urls:
        local = relative_path(url).as_posix()
        title = html_title(payloads[url], url)
        lines.append(
            f"- [[../resources/kamacoder-baguwen-v7/{local}|{title}]] · [在线页面]({url})"
        )
    lines.append(GENERATED_END)
    return "\n".join(lines)


def updated_wiki_bytes(path: Path, region: str) -> bytes:
    text = path.read_text(encoding="utf-8")
    if text.count(GENERATED_BEGIN) != 1 or text.count(GENERATED_END) != 1:
        raise ValueError("wiki index must contain exactly one generated snapshot region")
    begin = text.index(GENERATED_BEGIN)
    end = text.index(GENERATED_END, begin) + len(GENERATED_END)
    return (text[:begin] + region + text[end:]).encode("utf-8")


def build_tree(root: Path, payloads: dict[str, bytes]) -> None:
    expected: dict[Path, bytes] = {}
    for url, data in payloads.items():
        relative = relative_path(url)
        if relative in expected:
            raise ValueError(f"multiple URLs resolve to {relative}")
        expected[relative] = data
        target = resolved_target(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    actual = {
        path.relative_to(root) for path in root.rglob("*") if path.is_file()
    }
    if actual != set(expected):
        raise RuntimeError("temporary snapshot tree is incomplete")
    for relative, data in expected.items():
        if resolved_target(root, relative).read_bytes() != data:
            raise RuntimeError(f"temporary snapshot verification failed: {relative}")


def install_tree_and_index(output: Path, temporary_tree: Path, wiki_index: Path, wiki_data: bytes) -> None:
    requested_output = output.absolute()
    if has_symlink_component(requested_output):
        raise ValueError("managed snapshot output may not contain symbolic links")
    output = requested_output.resolve(strict=False)
    wiki_index = wiki_index.resolve(strict=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    if temporary_tree.is_symlink():
        raise ValueError("temporary snapshot root may not be a symbolic link")
    if wiki_index == output or wiki_index.is_relative_to(output):
        raise ValueError("wiki index must be outside the managed snapshot tree")

    descriptor, staged_index_name = tempfile.mkstemp(prefix=f".{wiki_index.name}.", dir=wiki_index.parent)
    backup: Path | None = None
    installed = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(wiki_data)
            handle.flush()
            os.fsync(handle.fileno())
        staged_index = Path(staged_index_name)
        if output.exists():
            if not output.is_dir():
                raise ValueError("managed snapshot output is not a directory")
            backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.backup.", dir=output.parent))
            backup.rmdir()
            os.replace(output, backup)
        try:
            os.replace(temporary_tree, output)
            installed = True
            os.replace(staged_index, wiki_index)
        except BaseException:
            if installed and output.exists():
                shutil.rmtree(output)
            if backup is not None and backup.exists():
                os.replace(backup, output)
            raise
        if backup is not None:
            shutil.rmtree(backup)
    finally:
        if os.path.exists(staged_index_name):
            os.unlink(staged_index_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--wiki-index", type=Path, default=DEFAULT_WIKI_INDEX)
    args = parser.parse_args()

    sitemap, sitemap_type = fetch(SITEMAP_URL)
    if "xml" not in sitemap_type.lower():
        raise RuntimeError(f"unexpected sitemap content type: {sitemap_type}")
    selected, lastmods = parse_sitemap(sitemap)
    if not selected:
        raise RuntimeError("sitemap contains no selected pages")
    if not all(lastmods.values()):
        raise RuntimeError("selected sitemap page is missing lastmod")

    urls = [ROBOTS_URL, ANNOUNCEMENT_URL, *selected]
    payloads: dict[str, bytes] = {SITEMAP_URL: sitemap}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch, url): url for url in urls}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            data, content_type = future.result()
            if url.endswith(".html") or urllib.parse.urlsplit(url).path.endswith("/"):
                if "html" not in content_type.lower():
                    raise RuntimeError(f"{url}: unexpected content type {content_type!r}")
            payloads[url] = data

    digest = snapshot_digest(payloads)
    counts = {
        prefix: sum(urllib.parse.urlsplit(url).path.startswith(prefix) for url in selected)
        for prefix in PREFIXES
    }
    region = generated_region(selected, lastmods, payloads, digest)
    wiki_data = updated_wiki_bytes(args.wiki_index, region)

    requested_output = args.output.absolute()
    if has_symlink_component(requested_output):
        raise ValueError("managed snapshot output may not contain symbolic links")
    output = requested_output.resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_tree = Path(tempfile.mkdtemp(prefix=f".{output.name}.new.", dir=output.parent))
    try:
        build_tree(temporary_tree, payloads)
        install_tree_and_index(requested_output, temporary_tree, args.wiki_index, wiki_data)
    finally:
        if temporary_tree.exists():
            shutil.rmtree(temporary_tree)

    summary = {
        "output": str(output),
        "html_pages": len(selected) + 1,
        "metadata_files": 2,
        "files_written": len(payloads),
        "bytes_written": sum(map(len, payloads.values())),
        "counts": counts,
        "latest_lastmod": max(lastmods.values()),
        "snapshot_sha256": digest,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"snapshot failed: {error}", file=sys.stderr)
        raise SystemExit(1)
