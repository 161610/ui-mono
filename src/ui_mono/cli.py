from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import sys

import typer

from ui_mono.app import build_registry, build_runtime
from ui_mono.config import (
    get_sessions_dir,
    has_anthropic_credentials,
    load_env,
)
from ui_mono.models.anthropic import AnthropicModelClient
from ui_mono.models.demo import (
    build_code_demo_model,
    CompactionDemoModelClient,
    EchoTurnModelClient,
    SequenceModelClient,
    tool_response,
)
from ui_mono.session.store import SessionStore
from ui_mono.types import AgentResponse
from ui_mono.runtime.events import build_runtime_event

app = typer.Typer(add_completion=False)


def resolve_session(session_store: SessionStore, resume: bool) -> Path:
    session_path = session_store.latest() if resume else None
    if session_path is None:
        session_path = session_store.create()
    return session_path


def load_session_state(session_store: SessionStore, session_path: Path) -> tuple[list[dict], str | None]:
    snapshot = session_store.load_snapshot(session_path)
    return snapshot.history, snapshot.summary


def create_chat_runtime(
    working_dir: Path,
    session_store: SessionStore,
    model: str,
    json_stream: bool,
    approval_callback=None,
):
    registry = build_registry(working_dir, approval_callback=approval_callback)
    model_client = AnthropicModelClient(model=model)
    return build_runtime(model_client, registry, session_store, event_sink=stream_sink(json_stream))


def run_single_prompt(
    working_dir: Path,
    session_store: SessionStore,
    session_path: Path,
    prompt: str,
    model: str,
    json_stream: bool,
) -> tuple[str, list[dict], str | None]:
    history, summary = load_session_state(session_store, session_path)
    runtime = create_chat_runtime(working_dir, session_store, model, json_stream)
    return runtime.run_turn(session_path, history, prompt, summary)


def render_tree(node, prefix: str = "") -> list[str]:
    label = f" [{node.branch_label}]" if node.branch_label else ""
    lines = [f"{prefix}{node.session_id}{label}"]
    for child in node.children:
        lines.extend(render_tree(child, prefix + "  "))
    return lines


def _echo(text: str) -> None:
    """Write text to stdout with UTF-8 encoding, bypassing the terminal's default codec on Windows."""
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write((text + "\n").encode("utf-8"))
        buf.flush()
    else:
        typer.echo(text)


def emit_output(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        _echo(json.dumps(payload, ensure_ascii=False))
        return
    for key, value in payload.items():
        if isinstance(value, list):
            _echo(f"{key}:")
            for item in value:
                _echo(f"- {item}")
        elif isinstance(value, dict):
            _echo(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            _echo(f"{key}: {value}")


def stream_sink(enabled: bool) -> callable:
    def sink(line: str) -> None:
        if enabled:
            _echo(line)

    return sink


def emit_runtime_event(enabled: bool, session_id: str, event: str, payload: dict[str, Any]) -> None:
    if not enabled:
        return
    _echo(build_runtime_event(event, session_id, payload).to_json())


def get_demo_sessions_dir(working_dir: Path) -> Path:
    return working_dir / ".ui-mono-demo-sessions"


def bootstrap_code_demo_workspace(working_dir: Path) -> tuple[Path, Path, Path]:
    workspace_dir = working_dir / ".ui-mono-code-demo"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    source_file = workspace_dir / "calculator.py"
    test_file = workspace_dir / "test_calculator.py"
    source_file.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b + 1\n",
        encoding="utf-8",
    )
    test_file.write_text(
        "from calculator import add\n\n\n"
        "def test_add() -> None:\n"
        "    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    return workspace_dir, source_file, test_file


def collect_tool_results(session_store: SessionStore, session_path: Path, tool_name: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    tool_calls: dict[str, dict[str, Any]] = {}
    for event in session_store.read_events(session_path):
        if event.type == "tool_call" and event.payload.get("name") == tool_name:
            tool_calls[event.payload["id"]] = event.payload
        elif event.type == "tool_result":
            tool_call = tool_calls.get(event.payload.get("id"))
            if tool_call and tool_call.get("name") == tool_name:
                results.append(
                    {
                        "id": event.payload.get("id"),
                        "tool": tool_name,
                        "input": tool_call.get("input"),
                        "content": event.payload.get("content", ""),
                        "status": "ok",
                    }
                )
        elif event.type == "tool_error":
            tool_call = tool_calls.get(event.payload.get("id"))
            if tool_call and tool_call.get("name") == tool_name:
                results.append(
                    {
                        "id": event.payload.get("id"),
                        "tool": tool_name,
                        "input": tool_call.get("input"),
                        "content": event.payload.get("error", ""),
                        "status": "error",
                    }
                )
    return results


def get_session_store(working_dir: Path, use_global: bool = True) -> SessionStore:
    if use_global:
        return SessionStore(get_sessions_dir())
    return SessionStore(get_demo_sessions_dir(working_dir))


def get_latest_summary(session_store: SessionStore) -> str | None:
    latest = session_store.latest()
    if latest is None:
        return None
    return session_store.load_snapshot(latest).summary


@app.command()
def chat(
    cwd: str = typer.Option(".", help="Working directory"),
    resume: bool = typer.Option(False, help="Resume latest session"),
    model: str = typer.Option("claude-opus-4-6", help="Anthropic model id"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    load_env(working_dir)
    if not has_anthropic_credentials():
        raise typer.BadParameter("Anthropic credentials are not set")

    session_store = SessionStore(get_sessions_dir())
    session_path = resolve_session(session_store, resume)
    history, summary = load_session_state(session_store, session_path)

    def _approval_cb(command: str, reason: str) -> bool:
        _echo(f"\n[approval required] {reason}")
        _echo(f"  command: {command}")
        return typer.confirm("Allow this command?", default=False)

    agent_loop = create_chat_runtime(working_dir, session_store, model, json_stream, approval_callback=_approval_cb)

    _echo(f"session: {session_path}")
    _echo("Type /quit to exit")
    _echo("Built-in commands: /branch <label>, /summary, /tree, /sessions, /inspect, /quit")

    while True:
        user_input = typer.prompt("you")
        if user_input.strip() == "/quit":
            break
        if user_input == "/summary":
            session_id = session_store.read_header(session_path).id
            payload = {"inspect": {"session": str(session_path), "summary": summary}}
            emit_runtime_event(json_stream, session_id, "inspect_summary", payload)
            if not json_stream:
                emit_output({"latest_summary": summary, "session": str(session_path)}, False)
            continue
        if user_input == "/inspect":
            snapshot = session_store.load_snapshot(session_path)
            payload = {
                "inspect": {
                    "session": str(session_path),
                    "session_id": snapshot.header.id,
                    "parent_id": snapshot.header.parent_id,
                    "branch_label": snapshot.header.branch_label,
                    "summary": snapshot.summary,
                    "history_size": len(snapshot.history),
                    "compaction": snapshot.compaction,
                }
            }
            emit_runtime_event(json_stream, snapshot.header.id, "inspect_session", payload)
            if not json_stream:
                emit_output(payload["inspect"], False)
            continue
        if user_input == "/tree":
            tree = session_store.build_tree()
            session_id = session_store.read_header(session_path).id
            payload = {"tree": {"nodes": [line for root in tree.roots for line in render_tree(root)]}}
            emit_runtime_event(json_stream, session_id, "session_tree", payload)
            if not json_stream:
                emit_output({"session_tree": payload["tree"]["nodes"]}, False)
            continue
        if user_input == "/sessions":
            items: list[dict[str, Any]] = []
            for listed_path in session_store.list_paths():
                header = session_store.read_header(listed_path)
                snapshot = session_store.load_snapshot(listed_path)
                items.append(
                    {
                        "session_id": header.id,
                        "path": str(listed_path),
                        "parent_id": header.parent_id,
                        "branch_label": header.branch_label,
                        "summary": snapshot.summary,
                        "message_count": len(snapshot.history),
                    }
                )
            session_id = session_store.read_header(session_path).id
            payload = {"sessions": {"items": items}}
            emit_runtime_event(json_stream, session_id, "session_list", payload)
            if not json_stream:
                emit_output({"sessions": items}, False)
            continue
        if user_input.startswith("/branch "):
            branch_label = user_input.removeprefix("/branch ").strip()
            if not branch_label:
                raise typer.BadParameter("branch label is required")
            session_path = session_store.fork(session_path, branch_label)
            history, summary = load_session_state(session_store, session_path)
            payload = {"branch": {"session": str(session_path), "label": branch_label}}
            emit_runtime_event(json_stream, session_store.read_header(session_path).id, "branch_created", payload)
            if not json_stream:
                emit_output({"branched": str(session_path), "branch_label": branch_label}, False)
            continue
        reply, history, summary = agent_loop.run_turn(session_path, history, user_input, summary)
        if reply and not json_stream:
            _echo(f"assistant> {reply}")


@app.command()
def run(
    prompt: str = typer.Option(..., help="Single prompt to execute"),
    cwd: str = typer.Option(".", help="Working directory"),
    resume: bool = typer.Option(False, help="Resume latest session"),
    model: str = typer.Option("claude-opus-4-6", help="Anthropic model id"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON object"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    load_env(working_dir)
    if not has_anthropic_credentials():
        raise typer.BadParameter("Anthropic credentials are not set")

    session_store = SessionStore(get_sessions_dir())
    session_path = resolve_session(session_store, resume)
    reply, history, summary = run_single_prompt(working_dir, session_store, session_path, prompt, model, json_stream)
    payload = {
        "inspect": {
            "session": str(session_path),
            "summary": summary,
            "reply": reply,
            "history_size": len(history),
        }
    }
    if json_output:
        emit_output(payload, True)
    elif not json_stream and reply:
        _echo(reply)


@app.command()
def code_demo(
    cwd: str = typer.Option(".", help="Working directory"),
    json_output: bool = typer.Option(False, "--json", help="Print final JSON object"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    session_store = get_session_store(working_dir, use_global=False)
    workspace_dir, source_file, test_file = bootstrap_code_demo_workspace(working_dir)
    pytest_command = f'"{sys.executable}" -m pytest test_calculator.py'
    registry = build_registry(workspace_dir)
    runtime = build_runtime(
        build_code_demo_model(source_file, test_file, pytest_command),
        registry,
        session_store,
        event_sink=stream_sink(json_stream),
    )
    session_path = session_store.create()
    history: list[dict[str, object]] = []
    summary: str | None = None
    reply = ""

    for prompt in [
        "inspect the buggy source file",
        "inspect the failing pytest file",
        "run pytest to capture the failure",
        "fix the buggy add function",
        "run pytest again to verify the fix",
    ]:
        reply, history, summary = runtime.run_turn(session_path, history, prompt, summary)

    bash_runs = collect_tool_results(session_store, session_path, "bash")
    payload = {
        "inspect": {
            "session": str(session_path),
            "source_file": str(source_file),
            "test_file": str(test_file),
            "workspace": str(workspace_dir),
            "reply": reply,
            "summary": summary,
        },
        "result": {
            "pytest_passed": any("1 passed" in run["content"] for run in bash_runs if run["status"] == "ok"),
            "bash_runs": bash_runs,
        },
        "events": {"items": [{"type": event.type, "payload": event.payload} for event in session_store.read_events(session_path)]},
    }
    emit_output(payload, json_output)


@app.command()
def demo(
    cwd: str = typer.Option(".", help="Working directory"),
    json_output: bool = typer.Option(False, "--json", help="Print final JSON object"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    session_store = get_session_store(working_dir, use_global=False)
    registry = build_registry(working_dir)
    runtime = build_runtime(
        SequenceModelClient(
            responses=[
                tool_response("demo-1", "write", {"path": "demo-notes.txt", "content": "hello from ui-mono\n"}),
                AgentResponse(text="created demo-notes.txt"),
                tool_response("demo-2", "read", {"path": "demo-notes.txt"}),
                AgentResponse(text="read demo-notes.txt"),
                tool_response("demo-3", "edit", {"path": "demo-notes.txt", "old": "hello", "new": "updated"}),
                AgentResponse(text="updated demo-notes.txt"),
                tool_response("demo-4", "read", {"path": "demo-notes.txt"}),
                AgentResponse(text="confirmed updated content"),
                tool_response("demo-5", "grep", {"path": ".", "pattern": "updated", "glob": "demo-notes.txt"}),
                AgentResponse(text="found updated line"),
                tool_response("demo-6", "read", {"path": "missing.txt"}),
                AgentResponse(text="captured missing file error"),
            ]
        ),
        registry,
        session_store,
        event_sink=stream_sink(json_stream),
    )
    session_path = session_store.create()
    history: list[dict[str, object]] = []
    summary: str | None = None

    for prompt in [
        "create the demo file",
        "read back the demo file",
        "update the demo file",
        "confirm the updated file content",
        "search for the updated line",
        "try reading a missing file so error handling is visible",
    ]:
        _, history, summary = runtime.run_turn(session_path, history, prompt, summary)

    payload = {
        "inspect": {
            "session": str(session_path),
            "file": str(working_dir / "demo-notes.txt"),
        },
        "sessions": {"items": [{"path": str(session_path)}]},
        "events": {"items": [{"type": event.type, "payload": event.payload} for event in session_store.read_events(session_path)]},
    }
    emit_output(payload, json_output)


@app.command()
def inspect_session(
    cwd: str = typer.Option(".", help="Working directory"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON object"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    session_store = get_session_store(working_dir, use_global=False)

    base_path = session_store.create()
    registry = build_registry(working_dir)
    runtime = build_runtime(CompactionDemoModelClient(), registry, session_store, event_sink=stream_sink(json_stream))
    history: list[dict[str, Any]] = []
    summary: str | None = None

    for index in range(7):
        _, history, summary = runtime.run_turn(base_path, history, f"base-{index}", summary)

    branch_path = session_store.fork(base_path, "experiment")
    branch_history, branch_summary = load_session_state(session_store, branch_path)
    branch_runtime = build_runtime(
        EchoTurnModelClient(),
        registry,
        session_store,
        event_sink=stream_sink(json_stream),
    )
    _, branch_history, branch_summary = branch_runtime.run_turn(
        branch_path,
        branch_history,
        "branch-follow-up",
        branch_summary,
    )

    resumed_history, resumed_summary = load_session_state(session_store, branch_path)
    tree = session_store.build_tree()
    base_events = session_store.read_events(base_path)
    branch_events = session_store.read_events(branch_path)

    payload = {
        "inspect": {
            "base_session": str(base_path),
            "branch_session": str(branch_path),
            "base_event_count": len(base_events),
            "branch_event_count": len(branch_events),
            "compaction_seen": any(event.type == "compaction" for event in base_events),
            "branch_event_seen": any(event.type == "branch" for event in branch_events),
            "branch_summary": resumed_summary,
            "resumed_history_size": len(resumed_history),
        },
        "tree": {"nodes": [line for root in tree.roots for line in render_tree(root)]},
    }
    emit_output(payload, json_output)


@app.command()
def rpc(
    cwd: str = typer.Option(".", help="Working directory"),
    resume: bool = typer.Option(False, help="Resume latest session"),
    model: str = typer.Option("claude-opus-4-6", help="Anthropic model id"),
) -> None:
    working_dir = Path(cwd).resolve()
    load_env(working_dir)
    if not has_anthropic_credentials():
        raise typer.BadParameter("Anthropic credentials are not set")

    session_store = SessionStore(get_sessions_dir())
    session_path = resolve_session(session_store, resume)

    while True:
        try:
            raw = input()
        except EOFError:
            break
        if not raw.strip():
            continue
        request = json.loads(raw)
        request_id = request.get("id")
        command = request.get("type")
        try:
            if command == "prompt":
                prompt = str(request.get("prompt", ""))
                reply, history, summary = run_single_prompt(working_dir, session_store, session_path, prompt, model, True)
                payload = {"request_id": request_id, "command": command, "result": {"reply": reply, "summary": summary, "history_size": len(history)}}
                _echo(build_runtime_event("rpc_response", session_store.read_header(session_path).id, payload).to_json())
            elif command == "summary":
                summary = get_latest_summary(session_store)
                payload = {"request_id": request_id, "command": command, "result": {"summary": summary}}
                _echo(build_runtime_event("rpc_response", session_store.read_header(session_path).id, payload).to_json())
            elif command == "inspect":
                snapshot = session_store.load_snapshot(session_path)
                payload = {
                    "request_id": request_id,
                    "command": command,
                    "result": {
                        "session_id": snapshot.header.id,
                        "parent_id": snapshot.header.parent_id,
                        "branch_label": snapshot.header.branch_label,
                        "summary": snapshot.summary,
                        "history_size": len(snapshot.history),
                        "compaction": snapshot.compaction,
                    },
                }
                _echo(build_runtime_event("rpc_response", snapshot.header.id, payload).to_json())
            elif command == "sessions":
                items: list[dict[str, Any]] = []
                for listed_path in session_store.list_paths():
                    header = session_store.read_header(listed_path)
                    snapshot = session_store.load_snapshot(listed_path)
                    items.append({"session_id": header.id, "path": str(listed_path), "summary": snapshot.summary})
                payload = {"request_id": request_id, "command": command, "result": {"sessions": items}}
                _echo(build_runtime_event("rpc_response", session_store.read_header(session_path).id, payload).to_json())
            elif command == "tree":
                tree = session_store.build_tree()
                payload = {"request_id": request_id, "command": command, "result": {"tree": [line for root in tree.roots for line in render_tree(root)]}}
                _echo(build_runtime_event("rpc_response", session_store.read_header(session_path).id, payload).to_json())
            elif command == "branch":
                label = str(request.get("label", "")).strip()
                if not label:
                    raise ValueError("branch label is required")
                session_path = session_store.fork(session_path, label)
                payload = {"request_id": request_id, "command": command, "result": {"session": str(session_path), "label": label}}
                _echo(build_runtime_event("rpc_response", session_store.read_header(session_path).id, payload).to_json())
            elif command == "new_session":
                session_path = session_store.create()
                payload = {"request_id": request_id, "command": command, "result": {"session": str(session_path)}}
                _echo(build_runtime_event("rpc_response", session_store.read_header(session_path).id, payload).to_json())
            else:
                raise ValueError(f"unknown rpc command: {command}")
        except Exception as exc:
            session_id = session_store.read_header(session_path).id
            payload = {"request_id": request_id, "command": command, "error": f"{type(exc).__name__}: {exc}"}
            _echo(build_runtime_event("rpc_error", session_id, payload).to_json())


@app.command("sessions-list")
def sessions_list(
    cwd: str = typer.Option(".", help="Working directory"),
    demo: bool = typer.Option(False, help="Browse demo sessions instead of chat sessions"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON object"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    session_store = get_session_store(working_dir, use_global=not demo)
    items: list[dict[str, Any]] = []
    for session_path in session_store.list_paths():
        header = session_store.read_header(session_path)
        snapshot = session_store.load_snapshot(session_path)
        items.append(
            {
                "session_id": header.id,
                "path": str(session_path),
                "parent_id": header.parent_id,
                "branch_label": header.branch_label,
                "summary": snapshot.summary,
                "message_count": len(snapshot.history),
            }
        )
    payload = {"sessions": {"items": items}}
    latest = session_store.latest()
    stream_session_id = session_store.read_header(latest).id if latest else "session-browser"
    emit_runtime_event(json_stream, stream_session_id, "session_list", payload)
    if not json_stream:
        emit_output({"sessions": {"items": items}}, json_output)


@app.command("sessions-summary")
def sessions_summary(
    cwd: str = typer.Option(".", help="Working directory"),
    demo: bool = typer.Option(False, help="Browse demo sessions instead of chat sessions"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON object"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    session_store = get_session_store(working_dir, use_global=not demo)
    latest = session_store.latest()
    payload = {
        "inspect": {
            "latest_session": str(latest) if latest else None,
            "latest_summary": get_latest_summary(session_store),
        }
    }
    stream_session_id = session_store.read_header(latest).id if latest else "session-browser"
    emit_runtime_event(json_stream, stream_session_id, "inspect_summary", payload)
    if not json_stream:
        emit_output(payload, json_output)


@app.command("sessions-tree")
def sessions_tree(
    cwd: str = typer.Option(".", help="Working directory"),
    demo: bool = typer.Option(False, help="Browse demo sessions instead of chat sessions"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON object"),
    json_stream: bool = typer.Option(False, "--json-stream", help="Stream runtime events as JSONL"),
) -> None:
    working_dir = Path(cwd).resolve()
    session_store = get_session_store(working_dir, use_global=not demo)
    tree = session_store.build_tree()
    payload = {"tree": {"nodes": [line for root in tree.roots for line in render_tree(root)]}}
    latest = session_store.latest()
    stream_session_id = session_store.read_header(latest).id if latest else "session-browser"
    emit_runtime_event(json_stream, stream_session_id, "session_tree", payload)
    if not json_stream:
        emit_output(payload, json_output)


if __name__ == "__main__":
    app()
