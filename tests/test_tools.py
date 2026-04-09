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
    result = bash_tool.execute({"command": f'"{sys.executable}" -c "print(\'ok\')"'})
    assert "ok" in result


def test_bash_tool_rejects_path_escape_cwd(tmp_path: Path) -> None:
    bash_tool = BashTool(tmp_path)
    with pytest.raises(ValueError, match="path escapes working directory"):
        bash_tool.execute({"command": f'"{sys.executable}" -c "print(\'ok\')"', "cwd": "../"})


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
