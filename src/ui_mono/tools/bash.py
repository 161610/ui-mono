from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from ui_mono.tools.policy import PolicyVerdict, ShellCommandPolicy, default_shell_command_policy
from ui_mono.tools_base import resolve_path


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

    def __init__(
        self,
        cwd: Path,
        policy: ShellCommandPolicy = default_shell_command_policy,
        approval_callback: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.cwd = cwd.resolve()
        self.policy = policy
        # approval_callback(command, reason) -> True=approved, False=denied
        self.approval_callback = approval_callback

    def execute(self, arguments: dict[str, str]) -> str:
        run_cwd = self.cwd
        raw_cwd = arguments.get("cwd")
        if raw_cwd:
            run_cwd = resolve_path(self.cwd, raw_cwd)
            if not run_cwd.is_dir():
                raise ValueError("cwd must be a directory")

        command = arguments["command"]
        result = self.policy.check(command)
        if result.verdict == PolicyVerdict.DENY:
            raise PermissionError(f"blocked by shell policy: {result.reason}")
        if result.verdict == PolicyVerdict.REQUIRE_APPROVAL:
            approved = self.approval_callback(command, result.reason) if self.approval_callback else False
            if not approved:
                raise PermissionError(f"blocked by shell policy: {result.reason} (denied)")

        result = subprocess.run(
            arguments["command"],
            cwd=run_cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout or "") + (result.stderr or "")
        rendered = output.strip()
        if result.returncode != 0:
            if rendered:
                return f"{rendered}\nCommand exited with code {result.returncode}"
            return f"Command exited with code {result.returncode}"
        return rendered or f"Command exited with code {result.returncode}"
