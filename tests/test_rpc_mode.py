from __future__ import annotations

from pathlib import Path
import json

from typer.testing import CliRunner

from ui_mono.cli import app, _echo
from ui_mono.models.demo import EchoTurnModelClient
from ui_mono.types import AgentResponse, ToolCall


class BlankThenToolRpcModel:
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
                            "content": [{"type": "tool_use", "id": "tool-1", "name": "write", "input": {"path": "a.txt", "content": "hello"}}],
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

    def generate(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> AgentResponse:
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[ToolCall(id="tool-1", name="write", input={"path": "a.txt", "content": "hello"})],
                content=[{"type": "tool_use", "id": "tool-1", "name": "write", "input": {"path": "a.txt", "content": "hello"}}],
            )
        return AgentResponse(text="done", content=[{"type": "text", "text": "done"}])


class LeadingWhitespaceRpcModel:
    def stream(self, messages: list[dict[str, object]], tools: list[dict[str, object]]):
        return iter(
            [
                {"type": "text_start", "payload": {}},
                {"type": "text_delta", "payload": {"delta": "\n\nHello"}},
                {"type": "text_delta", "payload": {"delta": " with RPC"}},
                {
                    "type": "message_done",
                    "payload": {
                        "text": "\n\nHello with RPC",
                        "tool_calls": [],
                        "content": [{"type": "text", "text": "\n\nHello with RPC"}],
                    },
                },
            ]
        )

    def generate(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> AgentResponse:
        return AgentResponse(text="Hello with RPC", content=[{"type": "text", "text": "Hello with RPC"}])


class DangerousBashRpcModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> AgentResponse:
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(tool_calls=[ToolCall(id="bash-1", name="bash", input={"command": "rm -rf ."})])
        tool_result = messages[-1]["content"][0]
        assert tool_result["is_error"] is True
        assert "blocked by shell policy" in tool_result["content"]
        return AgentResponse(text="blocked dangerous bash", content=[{"type": "text", "text": "blocked dangerous bash"}])


def test_echo_writes_utf8_bytes_for_non_ascii(monkeypatch) -> None:
    class DummyBuffer:
        def __init__(self) -> None:
            self.written = bytearray()
            self.flush_called = False

        def write(self, data: bytes) -> None:
            self.written.extend(data)

        def flush(self) -> None:
            self.flush_called = True

    class DummyStdout:
        def __init__(self) -> None:
            self.buffer = DummyBuffer()

    stdout = DummyStdout()
    monkeypatch.setattr("ui_mono.cli.sys.stdout", stdout)

    _echo("你好 👋")

    assert stdout.buffer.flush_called is True
    assert bytes(stdout.buffer.written) == "你好 👋\n".encode("utf-8")


def test_run_command_supports_text_json_and_stream(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: EchoTurnModelClient())

    text_result = runner.invoke(app, ["run", "--cwd", str(tmp_path), "--prompt", "hello"])
    json_result = runner.invoke(app, ["run", "--cwd", str(tmp_path), "--prompt", "hello", "--json"])
    stream_result = runner.invoke(app, ["run", "--cwd", str(tmp_path), "--prompt", "hello", "--json-stream"])

    assert text_result.exit_code == 0
    assert json_result.exit_code == 0
    assert stream_result.exit_code == 0
    assert text_result.output.strip()
    assert json.loads(json_result.output)["inspect"]["reply"]
    assert "turn_start" in stream_result.output


def test_run_command_resume_reuses_session(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: EchoTurnModelClient())

    first = runner.invoke(app, ["run", "--cwd", str(tmp_path), "--prompt", "one", "--json"])
    second = runner.invoke(app, ["run", "--cwd", str(tmp_path), "--prompt", "two", "--resume", "--json"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert json.loads(second.output)["inspect"]["history_size"] >= json.loads(first.output)["inspect"]["history_size"]


def test_rpc_mode_handles_prompt_and_summary(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: EchoTurnModelClient())

    rpc_input = "\n".join(
        [
            json.dumps({"id": "1", "type": "prompt", "prompt": "hello rpc"}),
            json.dumps({"id": "2", "type": "summary"}),
        ]
    )
    result = runner.invoke(app, ["rpc", "--cwd", str(tmp_path)], input=rpc_input)

    assert result.exit_code == 0
    assert "rpc_response" in result.output
    assert "turn_start" in result.output




def test_rpc_mode_handles_branch_and_sessions(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: EchoTurnModelClient())

    rpc_input = "\n".join(
        [
            json.dumps({"id": "1", "type": "new_session"}),
            json.dumps({"id": "2", "type": "branch", "label": "exp"}),
            json.dumps({"id": "3", "type": "sessions"}),
            json.dumps({"id": "4", "type": "tree"}),
        ]
    )
    result = runner.invoke(app, ["rpc", "--cwd", str(tmp_path)], input=rpc_input)

    assert result.exit_code == 0
    assert result.output.count("rpc_response") >= 4


def test_rpc_mode_trims_leading_whitespace_from_first_assistant_delta(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: LeadingWhitespaceRpcModel())

    rpc_input = json.dumps({"id": "1", "type": "prompt", "prompt": "hello rpc"})
    result = runner.invoke(app, ["rpc", "--cwd", str(tmp_path)], input=rpc_input)

    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines() if line.strip().startswith("{")]
    assistant_updates = [
        line["payload"]["message"]["delta"]
        for line in lines
        if line["event"] == "message_update" and line["payload"]["message"]["role"] == "assistant"
    ]
    assert assistant_updates == ["Hello", " with RPC"]
    assistant_end = next(
        line for line in lines if line["event"] == "message_end" and line["payload"]["message"]["role"] == "assistant"
    )
    assert assistant_end["payload"]["message"]["content"] == "Hello with RPC"
    assert lines[-1]["event"] == "rpc_response"
    assert lines[-1]["payload"]["result"]["reply"] == "Hello with RPC"



def test_rpc_mode_skips_blank_assistant_events_before_tool_call(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: BlankThenToolRpcModel())

    rpc_input = json.dumps({"id": "1", "type": "prompt", "prompt": "create a file"})
    result = runner.invoke(app, ["rpc", "--cwd", str(tmp_path)], input=rpc_input)

    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines() if line.strip().startswith("{")]
    tool_start_index = next(index for index, line in enumerate(lines) if line["event"] == "tool_execution_start")
    assert all(
        line["event"] != "message_start" or line["payload"]["message"].get("role") != "assistant"
        for line in lines[:tool_start_index]
    )
    assistant_updates = [
        line for line in lines if line["event"] == "message_update" and line["payload"]["message"]["role"] == "assistant"
    ]
    assistant_ends = [
        line for line in lines if line["event"] == "message_end" and line["payload"]["message"]["role"] == "assistant"
    ]
    assert [line["payload"]["message"]["delta"] for line in assistant_updates] == ["done"]
    assert [line["payload"]["message"]["content"] for line in assistant_ends] == ["done"]
    assert lines[-1]["event"] == "rpc_response"
    assert lines[-1]["payload"]["result"]["reply"] == "done"



def test_rpc_mode_reports_blocked_bash_as_tool_error(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: DangerousBashRpcModel())

    rpc_input = json.dumps({"id": "1", "type": "prompt", "prompt": "run dangerous bash"})
    result = runner.invoke(app, ["rpc", "--cwd", str(tmp_path)], input=rpc_input)

    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines() if line.strip().startswith("{")]
    tool_end = next(
        line
        for line in lines
        if line["event"] == "tool_execution_end" and line["payload"]["tool"]["name"] == "bash"
    )
    assert tool_end["payload"]["result"]["status"] == "error"
    assert "blocked by shell policy" in tool_end["payload"]["result"]["error"]
    rpc_response = next(line for line in reversed(lines) if line["event"] == "rpc_response")
    assert rpc_response["payload"]["result"]["reply"] == "blocked dangerous bash"
