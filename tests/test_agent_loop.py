from __future__ import annotations

from pathlib import Path
import json

from typer.testing import CliRunner

from ui_mono.agent_loop import AgentLoop
from ui_mono.app import build_registry, build_runtime
from ui_mono.cli import app
from ui_mono.session.store import SessionStore
from ui_mono.types import AgentResponse, ToolCall


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> AgentResponse:
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[ToolCall(id="tool-1", name="write", input={"path": "a.txt", "content": "hello"})]
            )
        return AgentResponse(text="done")


class BlankThenToolStreamModel:
    def __init__(self) -> None:
        self.calls = 0

    def stream(self, messages: list[dict[str, object]], tools: list[dict[str, object]]):
        self.calls += 1
        if self.calls == 1:
            return iter(
                [
                    {"type": "text_start", "payload": {}},
                    {"type": "text_delta", "payload": {"delta": "\n\n"}},
                    {
                        "type": "message_done",
                        "payload": {
                            "text": "",
                            "tool_calls": [{"id": "tool-1", "name": "write", "input": {"path": "a.txt", "content": "hello"}}],
                            "content": None,
                        },
                    },
                ]
            )
        return iter(
            [
                {"type": "text_start", "payload": {}},
                {"type": "text_delta", "payload": {"delta": "done"}},
                {"type": "message_done", "payload": {"text": "done", "tool_calls": [], "content": [{"type": "text", "text": "done"}]}},
            ]
        )


class LeadingWhitespaceStreamModel:
    def stream(self, messages: list[dict[str, object]], tools: list[dict[str, object]]):
        return iter(
            [
                {"type": "text_start", "payload": {}},
                {"type": "text_delta", "payload": {"delta": "\n\nHello"}},
                {"type": "text_delta", "payload": {"delta": " world"}},
                {
                    "type": "message_done",
                    "payload": {
                        "text": "\n\nHello world",
                        "tool_calls": [],
                        "content": [{"type": "text", "text": "\n\nHello world"}],
                    },
                },
            ]
        )


class EchoModel:
    def generate(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> AgentResponse:
        return AgentResponse(text=messages[-1]["content"])


class MissingToolModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> AgentResponse:
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(tool_calls=[ToolCall(id="missing-1", name="read", input={"path": "missing.txt"})])
        tool_result = messages[-1]["content"][0]
        assert tool_result["is_error"] is True
        assert "FileNotFoundError" in tool_result["content"]
        return AgentResponse(text="handled error")


class DangerousBashModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> AgentResponse:
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(tool_calls=[ToolCall(id="bash-1", name="bash", input={"command": "rm -rf ."})])
        tool_result = messages[-1]["content"][0]
        assert tool_result["is_error"] is True
        assert "blocked by shell policy" in tool_result["content"]
        return AgentResponse(text="blocked dangerous bash")


def test_agent_loop_streams_runtime_events(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    streamed: list[str] = []
    loop = build_runtime(FakeModel(), registry, store, event_sink=streamed.append)

    reply, _, _ = loop.run_turn(session_path, [], "create a file")

    assert reply == "done"
    events = [json.loads(line) for line in streamed]
    assert events[0]["event"] == "turn_start"
    assert all("timestamp" in event for event in events)
    assert events[0]["payload"]["turn"]["input"] == "create a file"
    assert any(event["event"] == "tool_execution_start" for event in events)
    assert any(event["event"] == "tool_execution_update" for event in events)
    assert any(event["event"] == "message_start" for event in events)
    updates = [event for event in events if event["event"] == "message_update"]
    assert len(updates) >= 2
    assert all("content" not in event["payload"]["message"] for event in updates)
    end_events = [event for event in events if event["event"] == "message_end"]
    assert any(
        event["payload"]["message"] == {"role": "user", "kind": "input", "content": "create a file"}
        for event in end_events
    )
    assert any(
        event["payload"]["message"] == {"role": "assistant", "kind": "response", "content": "done"}
        for event in end_events
    )
    tool_end = next(event for event in events if event["event"] == "tool_execution_end")
    assert tool_end["payload"]["tool"]["name"] == "write"
    assert tool_end["payload"]["result"]["status"] == "ok"
    assert events[-1]["event"] == "turn_end"
    assert events[-1]["payload"]["turn"]["reply"] == "done"


def test_agent_loop_suppresses_blank_assistant_events_before_tool_call(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    streamed: list[str] = []
    loop = build_runtime(BlankThenToolStreamModel(), registry, store, event_sink=streamed.append)

    reply, history, _ = loop.run_turn(session_path, [], "create a file")

    assert reply == "done"
    assistant_messages = [message for message in history if message["role"] == "assistant"]
    assert assistant_messages == [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "tool-1", "name": "write", "input": {"path": "a.txt", "content": "hello"}}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    ]
    events = [json.loads(line) for line in streamed]
    assistant_updates = [
        event for event in events if event["event"] == "message_update" and event["payload"]["message"]["role"] == "assistant"
    ]
    assistant_ends = [
        event for event in events if event["event"] == "message_end" and event["payload"]["message"]["role"] == "assistant"
    ]
    tool_start_index = next(index for index, event in enumerate(events) if event["event"] == "tool_execution_start")
    assert [event["payload"]["message"]["delta"] for event in assistant_updates] == ["done"]
    assert [event["payload"]["message"]["content"] for event in assistant_ends] == ["done"]
    assert all(event["payload"]["message"].get("delta", "").strip() for event in assistant_updates)
    assert all(
        event["event"] != "message_start" or event["payload"]["message"].get("role") != "assistant"
        for event in events[:tool_start_index]
    )
    persisted_messages = [event.payload for event in store.read_events(session_path) if event.type == "message"]
    assert [message for message in persisted_messages if message["role"] == "assistant"] == assistant_messages


def test_agent_loop_trims_leading_whitespace_from_first_assistant_delta(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    streamed: list[str] = []
    loop = build_runtime(LeadingWhitespaceStreamModel(), registry, store, event_sink=streamed.append)

    reply, history, _ = loop.run_turn(session_path, [], "hello")

    assert reply == "Hello world"
    assert history[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Hello world"}]}
    events = [json.loads(line) for line in streamed]
    assistant_updates = [
        event["payload"]["message"]["delta"]
        for event in events
        if event["event"] == "message_update" and event["payload"]["message"]["role"] == "assistant"
    ]
    assert assistant_updates == ["Hello", " world"]
    assistant_end = next(
        event for event in events if event["event"] == "message_end" and event["payload"]["message"]["role"] == "assistant"
    )
    assert assistant_end["payload"]["message"]["content"] == "Hello world"


def test_agent_loop_sanitizes_surrogate_input_before_model_call(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    loop = AgentLoop(EchoModel(), registry, store)

    reply, history, _ = loop.run_turn(session_path, [], "请\udcaf读取 README")

    assert reply == "请�读取 README"
    assert history[0] == {"role": "user", "content": "请�读取 README"}


def test_agent_loop_records_tool_error_and_returns_follow_up_text(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    loop = AgentLoop(MissingToolModel(), registry, store)

    reply, history, _ = loop.run_turn(session_path, [], "read a missing file")

    assert reply == "handled error"
    assert history[-1] == {"role": "assistant", "content": "handled error"}
    events = store.read_events(session_path)
    assert any(event.type == "tool_error" for event in events)


def test_agent_loop_records_blocked_bash_as_tool_error(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create()
    registry = build_registry(tmp_path)
    loop = AgentLoop(DangerousBashModel(), registry, store)

    reply, history, _ = loop.run_turn(session_path, [], "run a dangerous command")

    assert reply == "blocked dangerous bash"
    assert history[-1] == {"role": "assistant", "content": "blocked dangerous bash"}
    events = store.read_events(session_path)
    assert any(event.type == "tool_error" and "blocked by shell policy" in event.payload.get("error", "") for event in events)



def test_agent_loop_triggers_compaction_and_branch_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_path = store.create(parent_id="root-session", branch_label="experiment")
    registry = build_registry(tmp_path)
    loop = AgentLoop(EchoModel(), registry, store)

    history = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    reply, next_history, summary = loop.run_turn(session_path, history, "latest")

    assert reply == "latest"
    assert summary is not None
    assert len(next_history) <= 8
    events = store.read_events(session_path)
    assert any(event.type == "compaction" for event in events)
    assert any(event.type == "message" for event in events)


def test_demo_command_prints_tool_error_event(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert "tool_error" in result.output
    assert (tmp_path / "demo-notes.txt").read_text(encoding="utf-8") == "updated from ui-mono\n"


def test_demo_command_supports_json_output(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--cwd", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["inspect"]["file"].endswith("demo-notes.txt")
    assert payload["events"]["items"]


def test_demo_command_supports_json_stream(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--cwd", str(tmp_path), "--json-stream"])

    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines() if line.strip().startswith("{")]
    tool_error = next(line for line in lines if line["event"] == "tool_execution_end" and line["payload"]["result"].get("status") == "error")
    assert tool_error["payload"]["tool"]["name"] == "read"
    assert any(line["event"] == "compaction_start" for line in lines)
    text_updates = [line for line in lines if line["event"] == "message_update" and line["payload"]["message"]["role"] == "assistant"]
    assert len(text_updates) >= 2
    assert all("content" not in line["payload"]["message"] for line in text_updates)
    assistant_end_events = [
        line
        for line in lines
        if line["event"] == "message_end" and line["payload"]["message"]["role"] == "assistant"
    ]
    assert assistant_end_events
    assert any("content" in line["payload"]["message"] for line in assistant_end_events)
    assert assistant_end_events[-1]["payload"]["message"]["content"]
    assert all({"event", "timestamp", "session_id", "payload"}.issubset(line.keys()) for line in lines)
