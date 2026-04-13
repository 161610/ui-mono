from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ui_mono.runtime.agent_session import AgentSessionRuntime
from ui_mono.runtime.observer import JsonLineRuntimeObserver, NullRuntimeObserver, RuntimeEventDispatcher
from ui_mono.tools.bash import BashTool
from ui_mono.tools.edit import EditTool
from ui_mono.tools.find import FindTool
from ui_mono.tools.grep import GrepTool
from ui_mono.tools.ls import LsTool
from ui_mono.tools.policy import default_shell_command_policy
from ui_mono.tools.read import ReadTool
from ui_mono.tools.write import WriteTool
from ui_mono.tools_base import ToolRegistry
from ui_mono.models.base import ModelClient
from ui_mono.session.store import SessionStore


def build_registry(
    cwd: Path,
    approval_callback: Callable[[str, str], bool] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadTool(cwd))
    registry.register(WriteTool(cwd))
    registry.register(EditTool(cwd))
    registry.register(BashTool(cwd, policy=default_shell_command_policy, approval_callback=approval_callback))
    registry.register(LsTool(cwd))
    registry.register(FindTool(cwd))
    registry.register(GrepTool(cwd))
    return registry


def build_runtime(
    model_client: ModelClient,
    tool_registry: ToolRegistry,
    session_store: SessionStore,
    event_sink=None,
) -> AgentSessionRuntime:
    observer = JsonLineRuntimeObserver(event_sink) if event_sink is not None else NullRuntimeObserver()
    dispatcher = RuntimeEventDispatcher(observer)
    return AgentSessionRuntime(model_client, tool_registry, session_store, dispatcher=dispatcher)
