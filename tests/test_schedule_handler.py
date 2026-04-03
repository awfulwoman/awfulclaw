"""Tests for agent/handlers/schedule.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.bus import Bus, ScheduleEvent
from agent.connectors import OutboundEvent
from agent.handlers.schedule import ScheduleHandler
from agent.store import Schedule


def _make_schedule(
    *,
    id: str = "s1",
    name: str = "test",
    prompt: str = "summarise today",
    silent: bool = False,
) -> Schedule:
    return Schedule(
        id=id,
        name=name,
        cron=None,
        fire_at=None,
        prompt=prompt,
        silent=silent,
        tz="",
        created_at="2026-01-01T00:00:00+00:00",
        last_run=None,
    )


@pytest.mark.asyncio
async def test_fires_prompt_via_agent() -> None:
    """ScheduleHandler calls agent.invoke with the schedule's prompt."""
    agent = MagicMock()
    agent.invoke = AsyncMock(return_value="all good")

    bus = Bus()
    store = MagicMock()
    store.kv_get = AsyncMock(return_value=None)

    handler = ScheduleHandler(agent, bus, store)
    schedule = _make_schedule(prompt="check things", silent=True)
    await handler.handle(ScheduleEvent(schedule=schedule))

    agent.invoke.assert_called_once_with("check things")


@pytest.mark.asyncio
async def test_posts_outbound_when_not_silent() -> None:
    """Posts OutboundEvent to bus when silent=False and kv has channel/sender."""
    agent = MagicMock()
    agent.invoke = AsyncMock(return_value="hello there")

    bus = Bus()
    store = MagicMock()

    kv: dict[str, str] = {"last_channel": "tg:123", "last_sender": "charlie"}
    store.kv_get = AsyncMock(side_effect=lambda key: kv.get(key))

    handler = ScheduleHandler(agent, bus, store)
    schedule = _make_schedule(silent=False)
    await handler.handle(ScheduleEvent(schedule=schedule))

    assert not bus._queue.empty()
    event = bus._queue.get_nowait()
    assert isinstance(event, OutboundEvent)
    assert event.channel == "tg:123"
    assert event.to == "charlie"
    assert event.message.text == "hello there"


@pytest.mark.asyncio
async def test_discards_reply_when_silent() -> None:
    """Posts nothing to bus when schedule.silent=True."""
    agent = MagicMock()
    agent.invoke = AsyncMock(return_value="side effect only")

    bus = Bus()
    store = MagicMock()
    store.kv_get = AsyncMock(return_value="something")

    handler = ScheduleHandler(agent, bus, store)
    schedule = _make_schedule(silent=True)
    await handler.handle(ScheduleEvent(schedule=schedule))

    assert bus._queue.empty()


@pytest.mark.asyncio
async def test_no_outbound_when_kv_missing() -> None:
    """No OutboundEvent posted if kv has no last_channel/last_sender."""
    agent = MagicMock()
    agent.invoke = AsyncMock(return_value="reply text")

    bus = Bus()
    store = MagicMock()
    store.kv_get = AsyncMock(return_value=None)

    handler = ScheduleHandler(agent, bus, store)
    schedule = _make_schedule(silent=False)
    await handler.handle(ScheduleEvent(schedule=schedule))

    assert bus._queue.empty()
