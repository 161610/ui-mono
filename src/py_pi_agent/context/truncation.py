from __future__ import annotations

from typing import Any


def truncate_history(history: list[dict[str, Any]], max_messages: int = 12) -> list[dict[str, Any]]:
    if len(history) <= max_messages:
        return history
    return history[-max_messages:]
