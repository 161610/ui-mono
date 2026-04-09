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
