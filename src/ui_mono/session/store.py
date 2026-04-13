from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from ui_mono.session.schema import SessionHeader, SessionSnapshot, StoredEvent
from ui_mono.session.tree import SessionTree, SessionTreeNode


class SessionStore:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create(self, parent_id: str | None = None, branch_label: str | None = None) -> Path:
        session_id = str(uuid.uuid4())
        path = self.sessions_dir / f"{session_id}.jsonl"
        header = StoredEvent(
            type="session",
            payload={"id": session_id, "parent_id": parent_id, "branch_label": branch_label},
        )
        path.write_text(header.to_json() + "\n", encoding="utf-8")
        return path

    def latest(self) -> Path | None:
        files = self.list_paths()
        return files[0] if files else None

    def list_paths(self) -> list[Path]:
        return sorted(self.sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    def append(self, session_path: Path, event_type: str, payload: dict[str, Any]) -> None:
        with session_path.open("a", encoding="utf-8") as f:
            f.write(StoredEvent(type=event_type, payload=payload).to_json() + "\n")

    def read_events(self, session_path: Path) -> list[StoredEvent]:
        events: list[StoredEvent] = []
        for line in session_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(StoredEvent.from_json(line))
        return events

    def read_header(self, session_path: Path) -> SessionHeader:
        events = self.read_events(session_path)
        if not events:
            raise ValueError("session is empty")
        header_event = events[0]
        if header_event.type != "session":
            raise ValueError("session header missing")
        return SessionHeader(
            id=header_event.payload["id"],
            parent_id=header_event.payload.get("parent_id"),
            branch_label=header_event.payload.get("branch_label"),
        )

    def load_snapshot(self, session_path: Path) -> SessionSnapshot:
        events = self.read_events(session_path)
        if not events:
            raise ValueError("session is empty")
        header = self.read_header(session_path)
        history: list[dict[str, Any]] = []
        summary: str | None = None
        compaction: dict[str, Any] | None = None
        for event in events[1:]:
            if event.type == "message":
                history.append(event.payload)
            elif event.type == "tool_result":
                history.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": event.payload["id"],
                                "content": event.payload.get("content", ""),
                            }
                        ],
                    }
                )
            elif event.type == "tool_error":
                history.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": event.payload["id"],
                                "content": event.payload.get("error", ""),
                                "is_error": True,
                            }
                        ],
                    }
                )
            elif event.type == "summary":
                summary = event.payload.get("content")
            elif event.type == "compaction":
                compaction = event.payload
                kept_history = event.payload.get("kept_history")
                if isinstance(kept_history, list):
                    history = kept_history
                summary = event.payload.get("summary") or event.payload.get("content") or summary
        return SessionSnapshot(header=header, history=history, summary=summary, compaction=compaction)

    def load_history(self, session_path: Path) -> tuple[list[dict[str, Any]], str | None]:
        snapshot = self.load_snapshot(session_path)
        return snapshot.history, snapshot.summary

    def build_tree(self) -> SessionTree:
        tree = SessionTree()
        nodes: dict[str, SessionTreeNode] = {}
        for session_path in sorted(self.sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
            header = self.read_header(session_path)
            nodes[header.id] = SessionTreeNode(
                session_id=header.id,
                parent_id=header.parent_id,
                branch_label=header.branch_label,
                path=session_path,
            )
        for node in nodes.values():
            tree.attach(node)
        return tree

    def fork(self, session_path: Path, branch_label: str) -> Path:
        snapshot = self.load_snapshot(session_path)
        branch_path = self.create(parent_id=snapshot.header.id, branch_label=branch_label)
        self.append(
            branch_path,
            "branch",
            {
                "from_session_id": snapshot.header.id,
                "branch_label": branch_label,
                "source_session": session_path.name,
            },
        )
        for event in self.read_events(session_path)[1:]:
            self.append(branch_path, event.type, event.payload)
        return branch_path
