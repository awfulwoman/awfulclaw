from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.connectors import InboundEvent, Message, OutboundEvent
from agent.middleware import Middleware, Next
from agent.middleware.invoke import InvokeMiddleware
from agent.pipeline import Pipeline


def make_event(text: str = "hello") -> InboundEvent:
    return InboundEvent(
        channel="chan1",
        message=Message(text=text, sender="user1", sender_name="Alice"),
        connector_name="test",
    )


class RecordingMiddleware:
    def __init__(self, name: str, calls: list[str], short_circuit: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.short_circuit = short_circuit

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        self.calls.append(f"{self.name}:before")
        if not self.short_circuit:
            await next(event)
        self.calls.append(f"{self.name}:after")


@pytest.mark.asyncio
async def test_pipeline_calls_middleware_in_order() -> None:
    calls: list[str] = []
    m1 = RecordingMiddleware("m1", calls)
    m2 = RecordingMiddleware("m2", calls)
    m3 = RecordingMiddleware("m3", calls)

    pipeline = Pipeline([m1, m2, m3])
    await pipeline.run(make_event())

    assert calls == [
        "m1:before",
        "m2:before",
        "m3:before",
        "m3:after",
        "m2:after",
        "m1:after",
    ]


@pytest.mark.asyncio
async def test_pipeline_middleware_can_short_circuit() -> None:
    calls: list[str] = []
    m1 = RecordingMiddleware("m1", calls)
    m2 = RecordingMiddleware("m2", calls, short_circuit=True)
    m3 = RecordingMiddleware("m3", calls)

    pipeline = Pipeline([m1, m2, m3])
    await pipeline.run(make_event())

    assert "m3:before" not in calls
    assert "m1:before" in calls
    assert "m2:before" in calls


@pytest.mark.asyncio
async def test_pipeline_empty_middleware() -> None:
    pipeline = Pipeline([])
    await pipeline.run(make_event())  # Should not raise


@pytest.mark.asyncio
async def test_invoke_middleware_posts_outbound_event() -> None:
    event = make_event("hi")

    agent = MagicMock()
    agent.reply = AsyncMock(return_value="hello back")

    bus = MagicMock()
    bus.post = AsyncMock()

    mw = InvokeMiddleware(agent, bus)
    noop: Next = AsyncMock()

    await mw(event, noop)

    agent.reply.assert_called_once_with(event)
    bus.post.assert_called_once()
    posted: OutboundEvent = bus.post.call_args[0][0]
    assert isinstance(posted, OutboundEvent)
    assert posted.channel == "chan1"
    assert posted.to == "chan1"
    assert posted.message.text == "hello back"


@pytest.mark.asyncio
async def test_invoke_middleware_does_not_call_next() -> None:
    """InvokeMiddleware is terminal — it should not forward to next."""
    agent = MagicMock()
    agent.reply = AsyncMock(return_value="reply")

    bus = MagicMock()
    bus.post = AsyncMock()

    mw = InvokeMiddleware(agent, bus)
    next_fn: Next = AsyncMock()

    await mw(event=make_event(), next=next_fn)

    next_fn.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_with_invoke_middleware() -> None:
    """Integration: pipeline drives InvokeMiddleware and outbound event is posted."""
    event = make_event("question")

    agent = MagicMock()
    agent.reply = AsyncMock(return_value="answer")

    bus = MagicMock()
    bus.post = AsyncMock()

    pipeline = Pipeline([InvokeMiddleware(agent, bus)])
    await pipeline.run(event)

    bus.post.assert_called_once()
    posted: OutboundEvent = bus.post.call_args[0][0]
    assert posted.message.text == "answer"
