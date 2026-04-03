from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.connectors import InboundEvent, Message, OutboundMessage
from agent.middleware import Next
from agent.middleware.slash import SlashCommandMiddleware
from agent.store import Schedule


def make_event(text: str) -> InboundEvent:
    return InboundEvent(
        channel="chan",
        message=Message(text=text, sender="user1", sender_name="Alice"),
        connector_name="test",
    )


def make_mw() -> tuple[SlashCommandMiddleware, MagicMock, MagicMock]:
    connector = MagicMock()
    connector.send = AsyncMock()
    store = MagicMock()
    store.list_schedules = AsyncMock(return_value=[])
    mw = SlashCommandMiddleware(connector=connector, store=store)
    return mw, connector, store


@pytest.mark.asyncio
async def test_normal_message_passes_through() -> None:
    mw, connector, store = make_mw()
    next_fn: Next = AsyncMock()

    await mw(make_event("hello"), next_fn)

    next_fn.assert_called_once()
    connector.send.assert_not_called()


@pytest.mark.asyncio
async def test_schedules_empty() -> None:
    mw, connector, store = make_mw()
    next_fn: Next = AsyncMock()

    await mw(make_event("/schedules"), next_fn)

    next_fn.assert_not_called()
    connector.send.assert_called_once_with("chan", OutboundMessage(text="No schedules."))


@pytest.mark.asyncio
async def test_schedules_lists_items() -> None:
    mw, connector, store = make_mw()
    next_fn: Next = AsyncMock()
    store.list_schedules.return_value = [
        Schedule(id="1", name="daily", cron="0 9 * * *", fire_at=None, prompt="briefing",
                 silent=False, tz="UTC", created_at="2026-01-01", last_run=None),
    ]

    await mw(make_event("/schedules"), next_fn)

    next_fn.assert_not_called()
    sent = connector.send.call_args[0][1]
    assert "daily" in sent.text
    assert "0 9 * * *" in sent.text


@pytest.mark.asyncio
async def test_restart_short_circuits() -> None:
    mw, connector, store = make_mw()
    next_fn: Next = AsyncMock()

    await mw(make_event("/restart"), next_fn)

    next_fn.assert_not_called()
    connector.send.assert_called_once_with("chan", OutboundMessage(text="Restarting..."))


@pytest.mark.asyncio
async def test_unknown_slash_command_passes_through() -> None:
    mw, connector, store = make_mw()
    next_fn: Next = AsyncMock()

    await mw(make_event("/unknown"), next_fn)

    next_fn.assert_called_once()
    connector.send.assert_not_called()
