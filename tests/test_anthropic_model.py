from __future__ import annotations

from types import SimpleNamespace

from ui_mono.models import anthropic as anthropic_module


class FakeMessagesAPI:
    def __init__(self, stream_events: list[object], final_message: object) -> None:
        self.stream_events = stream_events
        self.final_message = final_message
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(self.stream_events)
        return self.final_message


class FakeAnthropicClient:
    def __init__(self, stream_events: list[object], final_message: object) -> None:
        self.messages = FakeMessagesAPI(stream_events, final_message)


def test_anthropic_stream_ignores_thinking_blocks(monkeypatch) -> None:
    stream_events = [
        SimpleNamespace(
            type="content_block_start",
            index=0,
            content_block=SimpleNamespace(type="text"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="text_delta", text="<th"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="text_delta", text="ink>internal reasoning</think>visible answer"),
        ),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(type="message_stop"),
    ]
    final_message = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="<think>internal reasoning</think>visible answer")]
    )
    fake_client = FakeAnthropicClient(stream_events, final_message)

    monkeypatch.setattr(anthropic_module, "Anthropic", lambda **kwargs: fake_client)
    monkeypatch.setattr(anthropic_module, "get_anthropic_client_kwargs", lambda: {})

    client = anthropic_module.AnthropicModelClient(model="test-model")
    events = list(client.stream(messages=[{"role": "user", "content": "hello"}], tools=[]))

    text_deltas = [event.payload["delta"] for event in events if event.type == "text_delta"]
    assert text_deltas == ["visible answer"]
    assert all("<think>" not in delta for delta in text_deltas)
    assert events[-1].type == "message_done"
    assert events[-1].payload["text"] == "visible answer"
    assert events[-1].payload["content"] == [{"type": "text", "text": "visible answer"}]
    # stream() should only issue one streaming request (no second create() call)
    assert len(fake_client.messages.calls) == 1
    assert fake_client.messages.calls[0].get("stream") is True
    assert "thinking" not in fake_client.messages.calls[0]
    assert "output_config" not in fake_client.messages.calls[0]


def test_anthropic_generate_omits_proxy_unsupported_fields(monkeypatch) -> None:
    stream_events: list[object] = []
    final_message = SimpleNamespace(content=[SimpleNamespace(type="text", text="hello")])
    fake_client = FakeAnthropicClient(stream_events, final_message)

    monkeypatch.setattr(anthropic_module, "Anthropic", lambda **kwargs: fake_client)
    monkeypatch.setattr(anthropic_module, "get_anthropic_client_kwargs", lambda: {})

    client = anthropic_module.AnthropicModelClient(model="test-model")
    response = client.generate(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert response.text == "hello"
    assert len(fake_client.messages.calls) == 1
    call = fake_client.messages.calls[0]
    assert call.get("stream") is None
    assert "thinking" not in call
    assert "output_config" not in call


def test_strip_think_tags_removes_visible_reasoning_markup() -> None:
    assert anthropic_module._strip_think_tags("prefix<think>hidden</think>suffix") == "prefixsuffix"
    assert anthropic_module._strip_think_tags("<think>hidden</think>") == ""
