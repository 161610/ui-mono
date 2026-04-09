from __future__ import annotations

from pathlib import Path
from typing import Any

from py_pi_agent.tools_base import resolve_path


class FindTool:
    name = "find"
    description = "Find files and directories by glob pattern"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pattern": {"type": "string"},
            "include_hidden": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "required": ["pattern"],
    }

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()

    def execute(self, arguments: dict[str, Any]) -> str:
        target = resolve_path(self.cwd, str(arguments.get("path", ".")))
        if not target.is_dir():
            raise ValueError("path must be a directory")

        pattern = str(arguments["pattern"])
        include_hidden = bool(arguments.get("include_hidden", False))
        limit = max(1, min(int(arguments.get("limit", 200)), 1000))

        matches = sorted(target.rglob(pattern), key=lambda p: p.relative_to(target).as_posix())
        lines: list[str] = []
        for entry in matches:
            rel = entry.relative_to(target)
            if not include_hidden and any(part.startswith(".") for part in rel.parts):
                continue
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{rel.as_posix()}{suffix}")
            if len(lines) >= limit:
                break

        return "\n".join(lines) if lines else "(no matches)"
