from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
EventType = Literal["session", "message", "tool_call", "tool_result", "summary"]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class AgentResponse:
    text: str = ""
    tool_calls: list[ToolCall] | None = None
    content: list[dict[str, Any]] | None = None


@dataclass
class SessionEvent:
    type: EventType
    payload: dict[str, Any]
