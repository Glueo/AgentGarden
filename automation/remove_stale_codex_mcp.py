#!/usr/bin/env python3
"""Remove the obsolete micu-image MCP section without exposing its old key."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path


def main() -> int:
    path = Path.home() / ".codex/config.toml"
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    output = []
    dropping = False
    changed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            dropping = section == "mcp_servers.micu-image" or section.startswith("mcp_servers.micu-image.")
            changed = changed or dropping
        if not dropping:
            output.append(line)
    if changed:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.agent-garden-{stamp}.bak"))
        temporary = path.with_suffix(".tmp")
        temporary.write_text("".join(output), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        print("Removed obsolete micu-image MCP configuration; rotate its former key at the provider.")
    else:
        print("Obsolete micu-image MCP configuration was already absent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

