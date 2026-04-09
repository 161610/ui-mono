from __future__ import annotations

from pathlib import Path
from typing import Any

from ui_mono.context.prompt_builder import build_messages
from ui_mono.context.truncation import truncate_history
from ui_mono.models.base import ModelClient
from ui_mono.session.schema import sanitize_value
from ui_mono.session.store import SessionStore
from ui_mono.session.summary import build_summary
from ui_mono.tools_base import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        session_store: SessionStore,
    ) -> None:
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.session_store = session_store

    def run_turn(
        self,
        session_path: Path,
        history: list[dict[str, Any]],
        user_input: str,
        summary: str | None = None,
    ) -> tuple[str, list[dict[str, Any]], str | None]:
        user_message = {"role": "user", "content": sanitize_value(user_input)}
        history = [*history, user_message]
        self.session_store.append(session_path, "message", user_message)

        final_text = ""
        while True:
            truncated_history = truncate_history(history)
            messages = build_messages(truncated_history, summary)
            response = self.model_client.generate(messages, self.tool_registry.as_anthropic_tools())

            assistant_content: str | list[dict[str, Any]]
            if response.content:
                assistant_content = sanitize_value(response.content)
            else:
                assistant_content = sanitize_value(response.text)

            assistant_message = {"role": "assistant", "content": assistant_content}
            history.append(assistant_message)
            self.session_store.append(session_path, "message", assistant_message)

            if response.text:
                final_text = sanitize_value(response.text)

            if not response.tool_calls:
                if len(history) > 12:
                    summary = build_summary(history[:-8])
                    self.session_store.append(session_path, "summary", {"content": summary})
                return final_text, history, summary

            for tool_call in response.tool_calls:
                self.session_store.append(
                    session_path,
                    "tool_call",
                    {"id": tool_call.id, "name": tool_call.name, "input": sanitize_value(tool_call.input)},
                )
                tool = self.tool_registry.get(tool_call.name)
                result = tool.execute(tool_call.input)
                tool_message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": sanitize_value(result),
                        }
                    ],
                }
                history.append(tool_message)
                self.session_store.append(
                    session_path,
                    "tool_result",
                    {"id": tool_call.id, "name": tool_call.name, "content": sanitize_value(result)},
                )
