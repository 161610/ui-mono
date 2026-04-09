from __future__ import annotations

from pathlib import Path

from py_pi_agent.tools.bash import BashTool
from py_pi_agent.tools.edit import EditTool
from py_pi_agent.tools.find import FindTool
from py_pi_agent.tools.grep import GrepTool
from py_pi_agent.tools.ls import LsTool
from py_pi_agent.tools.read import ReadTool
from py_pi_agent.tools.write import WriteTool
from py_pi_agent.tools_base import ToolRegistry


def build_registry(cwd: Path) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadTool(cwd))
    registry.register(WriteTool(cwd))
    registry.register(EditTool(cwd))
    registry.register(BashTool(cwd))
    registry.register(LsTool(cwd))
    registry.register(FindTool(cwd))
    registry.register(GrepTool(cwd))
    return registry
