from __future__ import annotations

from pathlib import Path

from ui_mono.runtime.agent_session import AgentSessionRuntime
from ui_mono.tools.bash import BashTool
from ui_mono.tools.edit import EditTool
from ui_mono.tools.find import FindTool
from ui_mono.tools.grep import GrepTool
from ui_mono.tools.ls import LsTool
from ui_mono.tools.read import ReadTool
from ui_mono.tools.write import WriteTool
from ui_mono.tools_base import ToolRegistry


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


def build_runtime(model_client, tool_registry: ToolRegistry, session_store) -> AgentSessionRuntime:
    return AgentSessionRuntime(model_client, tool_registry, session_store)
