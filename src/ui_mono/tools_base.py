from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    def execute(self, arguments: dict[str, Any]) -> str:
        ...


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    executor: callable


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def as_anthropic_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]


def resolve_path(cwd: Path, raw_path: str) -> Path:
    base = cwd.resolve()
    target = (base / raw_path).resolve()
    if target != base and base not in target.parents:
        raise ValueError("path escapes working directory")
    return target
