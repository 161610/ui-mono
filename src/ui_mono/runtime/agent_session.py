from __future__ import annotations

from pathlib import Path
from typing import Any

from ui_mono.context.prompt_builder import build_branch_messages
from ui_mono.context.truncation import trim_for_compaction, truncate_history
from ui_mono.models.base import ModelClient
from ui_mono.session.schema import sanitize_value
from ui_mono.session.store import SessionStore
from ui_mono.session.summary import build_compaction_summary, build_summary
from ui_mono.tools_base import ToolRegistry


class AgentSessionRuntime:
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
        session_state = self.session_store.load_snapshot(session_path)
        user_message = {"role": "user", "content": sanitize_value(user_input)}
        history = [*history, user_message]
        self.session_store.append(session_path, "message", user_message)

        final_text = ""
        while True:
            truncated_history = truncate_history(history)
            messages = build_branch_messages(
                truncated_history,
                summary=session_state.summary or summary,
                branch_label=session_state.header.branch_label,
                parent_id=session_state.header.parent_id,
            )
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
                removed_history, kept_history = trim_for_compaction(history)
                if removed_history:
                    summary = build_compaction_summary(removed_history, kept_history)
                    history = kept_history
                    self.session_store.append(
                        session_path,
                        "compaction",
                        {
                            "summary": summary,
                            "removed_count": len(removed_history),
                            "kept_count": len(kept_history),
                            "removed_history": sanitize_value(removed_history),
                            "kept_history": sanitize_value(kept_history),
                        },
                    )
                elif len(history) > 12:
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
