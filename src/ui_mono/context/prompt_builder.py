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


def build_branch_messages(
    history: list[dict[str, Any]],
    summary: str | None = None,
    branch_label: str | None = None,
    parent_id: str | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if parent_id or branch_label:
        branch_lines: list[str] = ["Branch context:"]
        if parent_id:
            branch_lines.append(f"parent session: {parent_id}")
        if branch_label:
            branch_lines.append(f"branch label: {branch_label}")
        messages.append({"role": "user", "content": "\n".join(branch_lines)})
    if summary:
        messages.append({"role": "user", "content": f"Session summary:\n{summary}"})
    messages.extend(history)
    return messages
