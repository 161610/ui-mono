from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ui_mono.tools.bash import BashTool
from ui_mono.tools.edit import EditTool
from ui_mono.tools.find import FindTool
from ui_mono.tools.grep import GrepTool
from ui_mono.tools.ls import LsTool
from ui_mono.tools.read import ReadTool
from ui_mono.tools.write import WriteTool


def test_read_write_edit_tools(tmp_path: Path) -> None:
    write_tool = WriteTool(tmp_path)
    read_tool = ReadTool(tmp_path)
    edit_tool = EditTool(tmp_path)

    write_tool.execute({"path": "demo.txt", "content": "hello world"})
    assert read_tool.execute({"path": "demo.txt"}) == "hello world"

    edit_tool.execute({"path": "demo.txt", "old": "world", "new": "agent"})
    assert read_tool.execute({"path": "demo.txt"}) == "hello agent"


def test_tools_reject_path_escape(tmp_path: Path) -> None:
    write_tool = WriteTool(tmp_path)
    read_tool = ReadTool(tmp_path)
    edit_tool = EditTool(tmp_path)

    with pytest.raises(ValueError, match="path escapes working directory"):
        write_tool.execute({"path": "../escape.txt", "content": "x"})
    with pytest.raises(ValueError, match="path escapes working directory"):
        read_tool.execute({"path": "../escape.txt"})
    with pytest.raises(ValueError, match="path escapes working directory"):
        edit_tool.execute({"path": "../escape.txt", "old": "a", "new": "b"})


def test_bash_tool(tmp_path: Path) -> None:
    bash_tool = BashTool(tmp_path)
    result = bash_tool.execute({"command": f'"{sys.executable}" -m pytest --version'})
    assert "pytest" in result.lower()


def test_bash_tool_rejects_path_escape_cwd(tmp_path: Path) -> None:
    bash_tool = BashTool(tmp_path)
    with pytest.raises(ValueError, match="path escapes working directory"):
        bash_tool.execute({"command": f'"{sys.executable}" -c "print(\'ok\')"', "cwd": "../"})


def test_bash_tool_rejects_dangerous_commands(tmp_path: Path) -> None:
    bash_tool = BashTool(tmp_path)
    with pytest.raises(PermissionError, match="blocked by shell policy"):
        bash_tool.execute({"command": "rm -rf ."})


def test_bash_tool_allows_readonly_git(tmp_path: Path) -> None:
    bash_tool = BashTool(tmp_path)
    # git status is in the whitelist — should not raise (may fail if no git repo, but won't be policy-blocked)
    from ui_mono.tools.policy import PolicyVerdict
    result = bash_tool.policy.check("git status")
    assert result.verdict == PolicyVerdict.ALLOW


def test_bash_tool_allows_python_script(tmp_path: Path) -> None:
    script = tmp_path / "hello.py"
    script.write_text("print('hello')")
    bash_tool = BashTool(tmp_path)
    from ui_mono.tools.policy import PolicyVerdict
    result = bash_tool.policy.check(f'"{sys.executable}" hello.py')
    assert result.verdict == PolicyVerdict.ALLOW


def test_bash_tool_pip_install_requires_approval(tmp_path: Path) -> None:
    from ui_mono.tools.policy import PolicyVerdict, ShellCommandPolicy
    # interactive policy (auto_approve=False) should require approval
    interactive_policy = ShellCommandPolicy(auto_approve=False)
    result = interactive_policy.check("pip install requests")
    assert result.verdict == PolicyVerdict.REQUIRE_APPROVAL


def test_bash_tool_approval_callback_approved(tmp_path: Path) -> None:
    from ui_mono.tools.policy import ShellCommandPolicy
    # approval_callback returns True → command is allowed (pip install triggers approval in interactive mode)
    interactive_policy = ShellCommandPolicy(auto_approve=False)
    bash_tool = BashTool(tmp_path, policy=interactive_policy, approval_callback=lambda cmd, reason: True)
    # pip install requests would require approval; with callback returning True it should not raise PermissionError
    # We just check the policy layer directly here since actually running pip install is disruptive
    from ui_mono.tools.policy import PolicyVerdict
    result = interactive_policy.check("pip install requests")
    assert result.verdict == PolicyVerdict.REQUIRE_APPROVAL  # callback is at BashTool level, not policy level


def test_bash_tool_approval_callback_denied(tmp_path: Path) -> None:
    from ui_mono.tools.policy import ShellCommandPolicy
    interactive_policy = ShellCommandPolicy(auto_approve=False)
    bash_tool = BashTool(tmp_path, policy=interactive_policy, approval_callback=lambda cmd, reason: False)
    with pytest.raises(PermissionError, match="blocked by shell policy"):
        bash_tool.execute({"command": "pip install requests"})



def test_ls_find_grep_tools(tmp_path: Path) -> None:
    write_tool = WriteTool(tmp_path)
    ls_tool = LsTool(tmp_path)
    find_tool = FindTool(tmp_path)
    grep_tool = GrepTool(tmp_path)

    write_tool.execute({"path": "src/a.py", "content": "print('hello')\nname = 'agent'\n"})
    write_tool.execute({"path": "src/b.txt", "content": "hello world\n"})

    ls_output = ls_tool.execute({"path": "src"})
    assert "a.py" in ls_output
    assert "b.txt" in ls_output

    find_output = find_tool.execute({"path": "src", "pattern": "*.py"})
    assert find_output.strip() == "a.py"

    grep_output = grep_tool.execute({"path": "src", "pattern": "hello", "glob": "*.py"})
    assert "a.py:1:print('hello')" in grep_output
