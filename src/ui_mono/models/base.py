from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ui_mono.types import AgentResponse


class ModelClient(ABC):
    @abstractmethod
    def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AgentResponse:
        raise NotImplementedError
