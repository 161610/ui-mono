from __future__ import annotations

from pathlib import Path

from py_pi_agent.tools_base import resolve_path


class EditTool:
    name = "edit"
    description = "Replace exact text in a file"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        "required": ["path", "old", "new"],
    }

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def execute(self, arguments: dict[str, str]) -> str:
        path = resolve_path(self.cwd, arguments["path"])
        text = path.read_text(encoding="utf-8")
        old = arguments["old"]
        if old not in text:
            raise ValueError("old text not found")
        path.write_text(text.replace(old, arguments["new"], 1), encoding="utf-8")
        return f"Edited {path}"
