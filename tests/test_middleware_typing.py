from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, call

from agent.connectors import InboundEvent, Message
from agent.middleware.typing import TypingMiddleware


def make_event(channel: str = "chan1") -> InboundEvent:
    return InboundEvent(
        channel=channel,
        message=Message(text="hello", sender="user1", sender_name="User"),
        connector_name="test",
    )


@pytest.mark.asyncio
async def test_typing_sent_before_next() -> None:
    call_order: list[str] = []

    connector = MagicMock()

    async def send_typing(channel: str) -> None:
        call_order.append("typing")

    connector.send_typing = send_typing

    async def next_mw(event: InboundEvent) -> None:
        call_order.append("next")

    mw = TypingMiddleware({"test": connector})
    await mw(make_event(), next_mw)

    assert call_order == ["typing", "next"]


@pytest.mark.asyncio
async def test_typing_uses_event_channel() -> None:
    connector = MagicMock()
    connector.send_typing = AsyncMock()

    async def next_mw(event: InboundEvent) -> None:
        pass

    mw = TypingMiddleware({"test": connector})
    event = make_event(channel="my-channel")
    await mw(event, next_mw)

    connector.send_typing.assert_called_once_with("my-channel")


@pytest.mark.asyncio
async def test_next_called_after_typing() -> None:
    connector = MagicMock()
    connector.send_typing = AsyncMock()
    next_mw = AsyncMock()

    mw = TypingMiddleware({"test": connector})
    event = make_event()
    await mw(event, next_mw)

    next_mw.assert_called_once_with(event)
