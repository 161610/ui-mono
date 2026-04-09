from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from py_pi_agent.session.schema import StoredEvent


class SessionStore:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> Path:
        session_id = str(uuid.uuid4())
        path = self.sessions_dir / f"{session_id}.jsonl"
        header = StoredEvent(type="session", payload={"id": session_id})
        path.write_text(header.to_json() + "\n", encoding="utf-8")
        return path

    def append(self, session_path: Path, event_type: str, payload: dict[str, Any]) -> None:
        with session_path.open("a", encoding="utf-8") as f:
            f.write(StoredEvent(type=event_type, payload=payload).to_json() + "\n")

    def read_events(self, session_path: Path) -> list[StoredEvent]:
        events: list[StoredEvent] = []
        for line in session_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(StoredEvent.from_json(line))
        return events

    def latest(self) -> Path | None:
        files = sorted(self.sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def load_history(self, session_path: Path) -> tuple[list[dict[str, Any]], str | None]:
        history: list[dict[str, Any]] = []
        summary: str | None = None
        for event in self.read_events(session_path):
            if event.type == "message":
                history.append(event.payload)
            elif event.type == "summary":
                summary = event.payload.get("content")
        return history, summary
