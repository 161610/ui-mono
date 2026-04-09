from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are a coding agent running in a local repository.
Use tools when needed.
Be concise, accurate, and safe.
Prefer reading files before editing them.
"""


def build_messages(history: list[dict[str, Any]], summary: str | None = None) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if summary:
        messages.append({"role": "user", "content": f"Session summary:\n{summary}"})
    messages.extend(history)
    return messages
