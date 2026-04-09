from __future__ import annotations

from typing import Any

from ui_mono.agent_loop import AgentLoop
from ui_mono.types import AgentResponse, ToolCall
from ui_mono.session.store import SessionStore
from ui_mono.app import build_registry


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AgentResponse:
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[ToolCall(id="tool-1", name="write", input={"path": "a.txt", "content": "hello"})]
            )
        return AgentResponse(text="done")


class EchoModel:
    def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AgentResponse:
        return AgentResponse(text=messages[-1]["content"])


def test_agent_loop_executes_tool_and_returns_text(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    loop = AgentLoop(FakeModel(), registry, store)

    reply, history, summary = loop.run_turn(session_path, [], "create a file")

    assert reply == "done"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
    assert summary is None
    assert any(item.get("role") == "assistant" for item in history)


def test_agent_loop_sanitizes_surrogate_input_before_model_call(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    loop = AgentLoop(EchoModel(), registry, store)

    reply, history, _ = loop.run_turn(session_path, [], "请\udcaf读取 README")

    assert reply == "请�读取 README"
    assert history[0] == {"role": "user", "content": "请�读取 README"}
