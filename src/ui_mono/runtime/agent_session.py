from __future__ import annotations

from pathlib import Path
from typing import Any

from ui_mono.context.prompt_builder import build_branch_messages
from ui_mono.context.truncation import trim_for_compaction, truncate_history
from ui_mono.models.base import ModelClient
from ui_mono.runtime.observer import NullRuntimeObserver, RuntimeEventDispatcher
from ui_mono.session.schema import sanitize_value
from ui_mono.session.store import SessionStore
from ui_mono.session.summary import build_compaction_summary, build_summary
from ui_mono.tools_base import ToolRegistry


def _trim_leading_assistant_text(text: str) -> str:
    return text.lstrip()


def _trim_leading_text_content(content: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not content:
        return content
    trimmed_content: list[dict[str, Any]] = []
    trim_leading = True
    for block in content:
        if trim_leading and block.get("type") == "text":
            trimmed_text = _trim_leading_assistant_text(str(block.get("text", "")))
            if trimmed_text:
                trimmed_content.append({**block, "text": trimmed_text})
                trim_leading = False
            continue
        trimmed_content.append(block)
        if block.get("type") == "text":
            trim_leading = False
    return trimmed_content


class AgentSessionRuntime:
    def __init__(
        self,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        session_store: SessionStore,
        dispatcher: RuntimeEventDispatcher | None = None,
    ) -> None:
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.session_store = session_store
        self.dispatcher = dispatcher or RuntimeEventDispatcher(NullRuntimeObserver())

    def emit(self, session_id: str, event: str, payload: dict[str, Any]) -> None:
        self.dispatcher.emit(event, session_id, sanitize_value(payload))

    def run_turn(
        self,
        session_path: Path,
        history: list[dict[str, Any]],
        user_input: str,
        summary: str | None = None,
    ) -> tuple[str, list[dict[str, Any]], str | None]:
        session_state = self.session_store.load_snapshot(session_path)
        session_id = session_state.header.id
        user_message = {"role": "user", "content": sanitize_value(user_input)}
        history = [*history, user_message]
        self.session_store.append(session_path, "message", user_message)
        self.emit(
            session_id,
            "turn_start",
            {
                "turn": {"input": user_message["content"]},
            },
        )
        self.emit(
            session_id,
            "message_start",
            {"message": {"role": "user", "kind": "input"}},
        )
        self.emit(
            session_id,
            "message_update",
            {"message": {"role": "user", "delta": user_message["content"]}},
        )
        self.emit(
            session_id,
            "message_end",
            {"message": {"role": "user", "kind": "input", "content": user_message["content"]}},
        )

        final_text = ""
        while True:
            truncated_history = truncate_history(history)
            messages = build_branch_messages(
                truncated_history,
                summary=session_state.summary or summary,
                branch_label=session_state.header.branch_label,
                parent_id=session_state.header.parent_id,
            )
            stream_method = getattr(self.model_client, "stream", None)
            if callable(stream_method):
                stream_events = stream_method(messages, self.tool_registry.as_anthropic_tools())
            else:
                response = self.model_client.generate(messages, self.tool_registry.as_anthropic_tools())
                stream_events = [
                    *(
                        [
                            {"type": "text_start", "payload": {}},
                            {"type": "text_delta", "payload": {"delta": response.text}},
                            {"type": "text_end", "payload": {}},
                        ]
                        if response.text
                        else []
                    ),
                    *(
                        [
                            {"type": "tool_call_start", "payload": {"id": tool_call.id, "name": tool_call.name}}
                            for tool_call in (response.tool_calls or [])
                        ]
                    ),
                    *(
                        [
                            {
                                "type": "tool_call_delta",
                                "payload": {"id": tool_call.id, "input": tool_call.input},
                            }
                            for tool_call in (response.tool_calls or [])
                        ]
                    ),
                    *(
                        [
                            {
                                "type": "tool_call_end",
                                "payload": {"id": tool_call.id, "name": tool_call.name, "input": tool_call.input},
                            }
                            for tool_call in (response.tool_calls or [])
                        ]
                    ),
                    {
                        "type": "message_done",
                        "payload": {
                            "text": response.text,
                            "tool_calls": [
                                {"id": tool_call.id, "name": tool_call.name, "input": tool_call.input}
                                for tool_call in (response.tool_calls or [])
                            ],
                            "content": response.content,
                        },
                    },
                ]

            assistant_started = False
            pending_assistant_prefix = ""
            final_message_text = ""
            final_message_content: list[dict[str, Any]] | None = None
            final_tool_calls: list[dict[str, Any]] = []

            for item in stream_events:
                if hasattr(item, "type"):
                    event_type = item.type
                    payload = item.payload
                else:
                    event_type = item["type"]
                    payload = item["payload"]
                if event_type == "text_delta":
                    delta = sanitize_value(str(payload.get("delta", "")))
                    if assistant_started:
                        self.emit(
                            session_id,
                            "message_update",
                            {"message": {"role": "assistant", "delta": delta}},
                        )
                    else:
                        pending_assistant_prefix += delta
                        visible_prefix = _trim_leading_assistant_text(pending_assistant_prefix)
                        if visible_prefix:
                            self.emit(
                                session_id,
                                "message_start",
                                {"message": {"role": "assistant", "kind": "response"}},
                            )
                            self.emit(
                                session_id,
                                "message_update",
                                {"message": {"role": "assistant", "delta": visible_prefix}},
                            )
                            assistant_started = True
                            pending_assistant_prefix = ""
                elif event_type == "message_done":
                    final_message_text = _trim_leading_assistant_text(sanitize_value(str(payload.get("text", "") or "")))
                    final_message_content = _trim_leading_text_content(sanitize_value(payload.get("content")))
                    final_tool_calls = sanitize_value(payload.get("tool_calls") or [])
                    if final_message_text:
                        if not assistant_started:
                            self.emit(
                                session_id,
                                "message_start",
                                {"message": {"role": "assistant", "kind": "response"}},
                            )
                            assistant_started = True
                        self.emit(
                            session_id,
                            "message_end",
                            {
                                "message": {
                                    "role": "assistant",
                                    "kind": "response",
                                    "content": final_message_text,
                                }
                            },
                        )
                elif event_type == "message_error":
                    raise RuntimeError(str(payload.get("error", "model stream failed")))

            assistant_content: str | list[dict[str, Any]]
            has_assistant_message = False
            if final_message_content:
                assistant_content = final_message_content
                has_assistant_message = True
            elif final_tool_calls:
                assistant_content = [
                    {
                        "type": "tool_use",
                        "id": str(tool_call_data["id"]),
                        "name": str(tool_call_data["name"]),
                        "input": sanitize_value(tool_call_data["input"]),
                    }
                    for tool_call_data in final_tool_calls
                ]
                has_assistant_message = True
            elif final_message_text:
                assistant_content = final_message_text
                has_assistant_message = True
            else:
                assistant_content = ""
            if has_assistant_message:
                assistant_message = {"role": "assistant", "content": assistant_content}
                history.append(assistant_message)
                self.session_store.append(session_path, "message", assistant_message)
            final_text = final_message_text

            if not final_tool_calls:
                removed_history, kept_history = trim_for_compaction(history)
                if removed_history:
                    self.emit(
                        session_id,
                        "compaction_start",
                        {
                            "compaction": {
                                "removed_count": len(removed_history),
                                "kept_count": len(kept_history),
                            }
                        },
                    )
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
                    self.emit(
                        session_id,
                        "compaction_end",
                        {
                            "compaction": {
                                "summary": summary,
                                "removed_count": len(removed_history),
                                "kept_count": len(kept_history),
                            }
                        },
                    )
                elif len(history) > 12:
                    summary = build_summary(history[:-8])
                    self.session_store.append(session_path, "summary", {"content": summary})
                    self.emit(session_id, "summary", {"summary": {"content": summary}})
                self.emit(session_id, "turn_end", {"turn": {"reply": final_text, "summary": summary}})
                return final_text, history, summary

            for tool_call_data in final_tool_calls:
                tool_id = str(tool_call_data["id"])
                tool_name = str(tool_call_data["name"])
                tool_input = sanitize_value(tool_call_data["input"])
                self.session_store.append(
                    session_path,
                    "tool_call",
                    {"id": tool_id, "name": tool_name, "input": tool_input},
                )
                self.emit(
                    session_id,
                    "tool_execution_start",
                    {"tool": {"id": tool_id, "name": tool_name, "input": tool_input}},
                )
                try:
                    tool = self.tool_registry.get(tool_name)
                    self.emit(
                        session_id,
                        "tool_execution_update",
                        {"tool": {"id": tool_id, "name": tool_name}, "result": {"status": "running"}},
                    )
                    result = tool.execute(tool_input)
                except Exception as exc:
                    error_message = sanitize_value(f"{type(exc).__name__}: {exc}")
                    self.session_store.append(
                        session_path,
                        "tool_error",
                        {"id": tool_id, "name": tool_name, "error": error_message},
                    )
                    self.emit(
                        session_id,
                        "tool_execution_end",
                        {
                            "tool": {"id": tool_id, "name": tool_name},
                            "result": {"status": "error", "error": error_message},
                        },
                    )
                    tool_message = {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": error_message,
                                "is_error": True,
                            }
                        ],
                    }
                else:
                    tool_message = {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": sanitize_value(result),
                            }
                        ],
                    }
                    self.session_store.append(
                        session_path,
                        "tool_result",
                        {"id": tool_id, "name": tool_name, "content": sanitize_value(result)},
                    )
                    self.emit(
                        session_id,
                        "tool_execution_end",
                        {
                            "tool": {"id": tool_id, "name": tool_name},
                            "result": {"status": "ok", "content": result},
                        },
                    )
                history.append(tool_message)
