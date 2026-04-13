from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ui_mono.runtime.events import RuntimeStreamEvent, utc_now_iso


class RuntimeObserver(Protocol):
    def emit(self, event: RuntimeStreamEvent) -> None:
        ...


class NullRuntimeObserver:
    def emit(self, event: RuntimeStreamEvent) -> None:
        return


class JsonLineRuntimeObserver:
    def __init__(self, sink) -> None:
        self.sink = sink

    def emit(self, event: RuntimeStreamEvent) -> None:
        self.sink(event.to_json())


@dataclass
class RuntimeEventDispatcher:
    observer: RuntimeObserver

    def emit(self, event: str, session_id: str, payload: dict[str, object]) -> None:
        self.observer.emit(
            RuntimeStreamEvent(
                event=event,
                timestamp=utc_now_iso(),
                session_id=session_id,
                payload=payload,
            )
        )
