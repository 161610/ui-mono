from __future__ import annotations

from typing import Any


def build_summary(history: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in history[-8:]:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        if isinstance(content, list):
            content = str(content)
        parts.append(f"[{role}] {str(content)[:200]}")
    return "\n".join(parts)


def build_compaction_summary(removed: list[dict[str, Any]], kept: list[dict[str, Any]]) -> str:
    removed_count = len(removed)
    kept_count = len(kept)
    preview = build_summary(removed)
    return f"compacted {removed_count} messages, kept {kept_count}\n{preview}"
