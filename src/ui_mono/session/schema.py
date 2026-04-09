from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


SURROGATE_START = 0xD800
SURROGATE_END = 0xDFFF


def sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return "".join(
            "\uFFFD" if SURROGATE_START <= ord(char) <= SURROGATE_END else char for char in value
        )
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_value(item) for key, item in value.items()}
    return value


@dataclass
class StoredEvent:
    type: str
    payload: dict[str, Any]

    def to_json(self) -> str:
        data = asdict(self)
        data["payload"] = sanitize_value(data["payload"])
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "StoredEvent":
        data = json.loads(line)
        return cls(type=data["type"], payload=data["payload"])
