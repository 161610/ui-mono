from __future__ import annotations

from pathlib import Path

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


def test_session_store_fork_records_branch_relationship(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_path = store.create()
    store.append(session_path, "message", {"role": "user", "content": "hello"})

    branch_path = store.fork(session_path, "fix-bug")
    snapshot = store.load_snapshot(branch_path)

    assert snapshot.header.parent_id == store.read_header(session_path).id
    assert snapshot.header.branch_label == "fix-bug"
    assert any(event.type == "branch" for event in store.read_events(branch_path))
