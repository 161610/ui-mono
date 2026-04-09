from __future__ import annotations

from pathlib import Path

from py_pi_agent.session.store import SessionStore


def test_session_store_create_append_and_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_path = store.create()
    store.append(session_path, "message", {"role": "user", "content": "hello"})
    store.append(session_path, "summary", {"content": "short summary"})

    history, summary = store.load_history(session_path)

    assert history == [{"role": "user", "content": "hello"}]
    assert summary == "short summary"


def test_session_store_sanitizes_surrogate_chars(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_path = store.create()
    broken_text = "请\udcaf读取 README"

    store.append(session_path, "message", {"role": "user", "content": broken_text})

    history, _ = store.load_history(session_path)

    assert history == [{"role": "user", "content": "请�读取 README"}]
