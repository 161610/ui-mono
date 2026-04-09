from __future__ import annotations

import subprocess
from pathlib import Path

from py_pi_agent.tools_base import resolve_path


class BashTool:
    name = "bash"
    description = "Run a shell command"
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string"},
        },
        "required": ["command"],
    }

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()

    def execute(self, arguments: dict[str, str]) -> str:
        run_cwd = self.cwd
        raw_cwd = arguments.get("cwd")
        if raw_cwd:
            run_cwd = resolve_path(self.cwd, raw_cwd)
            if not run_cwd.is_dir():
                raise ValueError("cwd must be a directory")

        result = subprocess.run(
            arguments["command"],
            cwd=run_cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip() or f"Command exited with code {result.returncode}"
