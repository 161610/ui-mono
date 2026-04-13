from __future__ import annotations

from pathlib import Path
import json

from typer.testing import CliRunner

from ui_mono.cli import app
from ui_mono.session.store import SessionStore


def test_session_store_create_append_and_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_path = store.create()
    store.append(session_path, "message", {"role": "user", "content": "hello"})
    store.append(session_path, "summary", {"content": "short summary"})

    snapshot = store.load_snapshot(session_path)

    assert snapshot.history == [{"role": "user", "content": "hello"}]
    assert snapshot.summary == "short summary"
    assert snapshot.header.parent_id is None


def test_session_store_sanitizes_surrogate_chars(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_path = store.create()
    broken_text = "请\udcaf读取 README"

    store.append(session_path, "message", {"role": "user", "content": broken_text})

    history, _ = store.load_history(session_path)

    assert history == [{"role": "user", "content": "请�读取 README"}]


def test_session_store_load_snapshot_restores_tool_error_message(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_path = store.create()
    store.append(session_path, "tool_error", {"id": "tool-1", "name": "read", "error": "FileNotFoundError: missing"})

    snapshot = store.load_snapshot(session_path)

    assert snapshot.history == [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": "FileNotFoundError: missing",
                    "is_error": True,
                }
            ],
        }
    ]


def test_session_store_fork_records_branch_relationship(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_path = store.create()
    store.append(session_path, "message", {"role": "user", "content": "hello"})

    branch_path = store.fork(session_path, "fix-bug")
    snapshot = store.load_snapshot(branch_path)

    assert snapshot.header.parent_id == store.read_header(session_path).id
    assert snapshot.header.branch_label == "fix-bug"
    assert any(event.type == "branch" for event in store.read_events(branch_path))


def test_session_tree_supports_multiple_roots(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    first = store.create()
    second = store.create()
    store.fork(first, "branch-a")

    tree = store.build_tree()

    assert len(tree.roots) == 2
    assert tree.find(store.read_header(second).id) is not None


def test_inspect_session_command_shows_resume_branch_and_compaction(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["inspect-session", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert 'compaction_seen": true' in result.output.lower()
    assert 'branch_event_seen": true' in result.output.lower()
    assert "tree:" in result.output


def test_inspect_session_command_supports_json_output(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["inspect-session", "--cwd", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["inspect"]["compaction_seen"] is True
    assert payload["inspect"]["branch_event_seen"] is True
    assert payload["tree"]["nodes"]


def test_session_browser_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    inspect_result = runner.invoke(app, ["inspect-session", "--cwd", str(tmp_path)])

    list_result = runner.invoke(app, ["sessions-list", "--cwd", str(tmp_path), "--demo", "--json"])
    summary_result = runner.invoke(app, ["sessions-summary", "--cwd", str(tmp_path), "--demo", "--json"])
    tree_result = runner.invoke(app, ["sessions-tree", "--cwd", str(tmp_path), "--demo", "--json"])
    list_stream_result = runner.invoke(app, ["sessions-list", "--cwd", str(tmp_path), "--demo", "--json-stream"])

    assert inspect_result.exit_code == 0
    assert list_result.exit_code == 0
    assert summary_result.exit_code == 0
    assert tree_result.exit_code == 0
    assert list_stream_result.exit_code == 0

    list_payload = json.loads(list_result.output)
    summary_payload = json.loads(summary_result.output)
    tree_payload = json.loads(tree_result.output)
    list_stream_payload = json.loads(list_stream_result.output)

    assert len(list_payload["sessions"]["items"]) >= 2
    assert summary_payload["inspect"]["latest_session"] is not None
    assert tree_payload["tree"]["nodes"]
    assert list_stream_payload["event"] == "session_list"
    assert len(list_stream_payload["payload"]["sessions"]["items"]) >= 2


def test_chat_builtin_inspect_commands(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from ui_mono import cli as cli_module

    class StubRuntime:
        def run_turn(self, session_path, history, user_input, summary=None):
            return "ok", history + [{"role": "assistant", "content": "ok"}], summary

    class StubModelClient:
        pass

    monkeypatch.setattr(cli_module, "has_anthropic_credentials", lambda: True)
    monkeypatch.setattr(cli_module, "load_env", lambda cwd: None)
    monkeypatch.setattr(cli_module, "AnthropicModelClient", lambda model: StubModelClient())
    monkeypatch.setattr(cli_module, "build_runtime", lambda *args, **kwargs: StubRuntime())

    result = runner.invoke(
        app,
        ["chat", "--cwd", str(tmp_path), "--json-stream"],
        input="/summary\n/inspect\n/tree\n/sessions\n/quit\n",
    )

    assert result.exit_code == 0
    assert "inspect_summary" in result.output
    assert "session_tree" in result.output
    assert "session_list" in result.output
