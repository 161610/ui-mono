from __future__ import annotations

from typing import Any

from anthropic import Anthropic

from ui_mono.config import get_anthropic_client_kwargs
from ui_mono.context.prompt_builder import SYSTEM_PROMPT
from ui_mono.types import AgentResponse, ToolCall
from ui_mono.models.base import ModelClient


class AnthropicModelClient(ModelClient):
    def __init__(self, model: str = "claude-opus-4-6") -> None:
        self.client = Anthropic(**get_anthropic_client_kwargs())
        self.model = model

    def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AgentResponse:
        response = self.client.messages.create(
            model=self.model,
            system=SYSTEM_PROMPT,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=messages,
            tools=tools,
        )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        content_blocks: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                content_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
                content_blocks.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
        return AgentResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls or None,
            content=content_blocks or None,
        )
