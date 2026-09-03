#!/usr/bin/env python3
"""Re-appliable Hermes source patches for the Agent Garden runtime.

Hermes is installed as a git checkout and ``hermes update`` runs ``git pull``
with a ``git reset --hard HEAD`` rollback, so anything edited in place is
eventually discarded.  Every patch here is therefore written to be idempotent
and is re-applied by ``install_runtime.py`` on each run: after an update, one
``install_runtime`` pass restores them.

Only add a patch here when configuration genuinely cannot express the change.
Each entry documents why.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

HOME = Path.home()
HERMES_SOURCE = HOME / ".hermes/hermes-agent"

# ── context-1m opt-in for Anthropic-compatible relays ──────────────────
# Relays that front Claude behind the Messages API (anyrouter and friends)
# reject every request with HTTP 400 ("请启用 1m 上下文") unless the client
# sends ``anthropic-beta: context-1m-2025-08-07``.  Hermes derives that beta
# from the base URL alone and only for ``azure.com``.  No configuration key
# reaches this path: ``build_anthropic_client`` constructs the Messages
# client itself, and run_agent skips ``custom_providers[].extra_headers``
# (and ``model.default_headers``) for ``api_mode: anthropic_messages``.
#
# The patch adds a ``context_1m_beta: true`` opt-in on the provider entry, so
# future relays are pure configuration and need no further source edit.
_CONTEXT_1M_HELPER = '''def _config_opts_into_context_1m_beta(base_url: str | None) -> bool:
    """True when a custom_providers entry for this host sets ``context_1m_beta``.

    Anthropic-compatible relays commonly gate their 1M window behind
    ``context-1m-2025-08-07`` and reject everything else with HTTP 400. That
    beta is otherwise URL-derived (Azure only), and this construction path
    never sees per-provider ``extra_headers``, so the provider flag is the
    only place a user can express the opt-in.

    Matched on HOSTNAME, not the full URL: ``build_anthropic_client``
    normalizes the configured ``https://relay/v1`` down to ``https://relay``
    before asking for betas, so a whole-URL comparison never fires. Read once
    per process -- a config change needs a restart.
    """
    global _CONTEXT_1M_OPT_IN_HOSTS
    if _CONTEXT_1M_OPT_IN_HOSTS is None:
        hosts = set()
        try:
            from hermes_cli.config import load_config

            providers = load_config().get("custom_providers")
            for entry in providers if isinstance(providers, list) else []:
                if not isinstance(entry, dict) or not entry.get("context_1m_beta"):
                    continue
                host = base_url_hostname(
                    _normalize_base_url_text(entry.get("base_url"))
                ).lower()
                if host:
                    hosts.add(host)
        except Exception:  # noqa: BLE001 - never break client construction
            hosts = set()
        _CONTEXT_1M_OPT_IN_HOSTS = frozenset(hosts)
    if not _CONTEXT_1M_OPT_IN_HOSTS:
        return False
    host = base_url_hostname(_normalize_base_url_text(base_url)).lower()
    return bool(host) and host in _CONTEXT_1M_OPT_IN_HOSTS


_CONTEXT_1M_OPT_IN_HOSTS = None


'''

_CONTEXT_1M_OLD_GATE = """    betas = list(_COMMON_BETAS)
    if _base_url_needs_context_1m_beta(base_url) and not drop_context_1m_beta:
        betas.append(_CONTEXT_1M_BETA)
"""

_CONTEXT_1M_NEW_GATE = """    betas = list(_COMMON_BETAS)
    if (
        _base_url_needs_context_1m_beta(base_url)
        or _config_opts_into_context_1m_beta(base_url)
    ) and not drop_context_1m_beta:
        betas.append(_CONTEXT_1M_BETA)
"""

_CONTEXT_1M_ANCHOR = "def _common_betas_for_base_url(\n"

# marker -> (relative path, edits); an edit is (old, new).
PATCHES: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "_config_opts_into_context_1m_beta": (
        "agent/anthropic_adapter.py",
        (
            (_CONTEXT_1M_ANCHOR, _CONTEXT_1M_HELPER + _CONTEXT_1M_ANCHOR),
            (_CONTEXT_1M_OLD_GATE, _CONTEXT_1M_NEW_GATE),
        ),
    ),
}


def backup(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path.with_name(f"{path.name}.agent-garden-{stamp}.bak").write_bytes(path.read_bytes())


def apply_patch(source: str, marker: str, edits: tuple[tuple[str, str], ...]) -> str:
    """Return ``source`` with ``edits`` applied, or unchanged if already patched.

    Raises when an anchor is missing or ambiguous: a silently skipped patch
    would leave Hermes sending requests the relay rejects, which surfaces much
    later as an opaque provider error.
    """
    if marker in source:
        return source
    for old, new in edits:
        found = source.count(old)
        if found != 1:
            raise RuntimeError(
                f"Hermes source patch {marker!r}: anchor matched {found} times, expected 1. "
                "Upstream changed; re-check the patch against the new source."
            )
        source = source.replace(old, new)
    return source


def main(hermes_source: Path | None = None) -> list[str]:
    """Apply every patch to the Hermes checkout; returns the applied markers."""
    root = hermes_source or HERMES_SOURCE
    applied: list[str] = []
    for marker, (relative, edits) in PATCHES.items():
        target = root / relative
        if not target.exists():
            raise RuntimeError(f"Hermes source file missing: {target}")
        original = target.read_text(encoding="utf-8")
        patched = apply_patch(original, marker, edits)
        if patched == original:
            continue
        backup(target)
        target.write_text(patched, encoding="utf-8")
        applied.append(marker)
    return applied


if __name__ == "__main__":
    for name in main():
        print(f"Applied Hermes source patch: {name}")
