from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from ui_mono.models.streaming import ModelStreamEvent
from ui_mono.types import AgentResponse


class ModelClient(ABC):
    @abstractmethod
    def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AgentResponse:
        raise NotImplementedError

    def stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Iterable[ModelStreamEvent]:
        response = self.generate(messages, tools)
        if response.text:
            yield ModelStreamEvent(type="text_start", payload={})
            yield ModelStreamEvent(type="text_delta", payload={"delta": response.text})
            yield ModelStreamEvent(type="text_end", payload={})
        if response.tool_calls:
            for tool_call in response.tool_calls:
                yield ModelStreamEvent(type="tool_call_start", payload={"id": tool_call.id, "name": tool_call.name})
                yield ModelStreamEvent(type="tool_call_delta", payload={"id": tool_call.id, "input": tool_call.input})
                yield ModelStreamEvent(
                    type="tool_call_end",
                    payload={"id": tool_call.id, "name": tool_call.name, "input": tool_call.input},
                )
        yield ModelStreamEvent(
            type="message_done",
            payload={
                "text": response.text,
                "tool_calls": [
                    {"id": tool_call.id, "name": tool_call.name, "input": tool_call.input}
                    for tool_call in (response.tool_calls or [])
                ],
                "content": response.content,
            },
        )
