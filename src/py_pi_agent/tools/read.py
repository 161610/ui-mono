from __future__ import annotations

from pathlib import Path

from py_pi_agent.tools_base import resolve_path


class ReadTool:
    name = "read"
    description = "Read a file from disk"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def execute(self, arguments: dict[str, str]) -> str:
        path = resolve_path(self.cwd, arguments["path"])
        return path.read_text(encoding="utf-8")
