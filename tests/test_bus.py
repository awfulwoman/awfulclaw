from __future__ import annotations

import asyncio
import pytest

from agent.bus import Bus, ScheduleEvent
from agent.connectors import InboundEvent, OutboundEvent, Message, OutboundMessage


def make_inbound() -> InboundEvent:
    return InboundEvent(
        channel="chan1",
        message=Message(text="hi", sender="u1", sender_name="User"),
        connector_name="test",
    )


def make_outbound() -> OutboundEvent:
    return OutboundEvent(
        channel="chan1",
        to="u1",
        message=OutboundMessage(text="hello"),
    )


@pytest.mark.asyncio
async def test_post_and_receive_inbound() -> None:
    bus = Bus()
    received: list[InboundEvent] = []

    async def handler(event: InboundEvent) -> None:
        received.append(event)

    bus.subscribe(InboundEvent, handler)
    event = make_inbound()
    await bus.post(event)

    async def run_once() -> None:
        await asyncio.wait_for(bus.run(), timeout=0.1)

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await run_once()

    assert received == [event]


@pytest.mark.asyncio
async def test_post_and_receive_outbound() -> None:
    bus = Bus()
    received: list[OutboundEvent] = []

    async def handler(event: OutboundEvent) -> None:
        received.append(event)

    bus.subscribe(OutboundEvent, handler)
    event = make_outbound()
    await bus.post(event)

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(bus.run(), timeout=0.1)

    assert received == [event]


@pytest.mark.asyncio
async def test_multiple_subscribers_same_type() -> None:
    bus = Bus()
    calls: list[str] = []

    async def h1(event: InboundEvent) -> None:
        calls.append("h1")

    async def h2(event: InboundEvent) -> None:
        calls.append("h2")

    bus.subscribe(InboundEvent, h1)
    bus.subscribe(InboundEvent, h2)
    await bus.post(make_inbound())

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(bus.run(), timeout=0.1)

    assert calls == ["h1", "h2"]


@pytest.mark.asyncio
async def test_correct_type_routing() -> None:
    bus = Bus()
    inbound_calls: list[InboundEvent] = []
    outbound_calls: list[OutboundEvent] = []

    async def inbound_handler(event: InboundEvent) -> None:
        inbound_calls.append(event)

    async def outbound_handler(event: OutboundEvent) -> None:
        outbound_calls.append(event)

    bus.subscribe(InboundEvent, inbound_handler)
    bus.subscribe(OutboundEvent, outbound_handler)

    inbound = make_inbound()
    outbound = make_outbound()
    await bus.post(inbound)
    await bus.post(outbound)

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(bus.run(), timeout=0.1)

    assert inbound_calls == [inbound]
    assert outbound_calls == [outbound]


@pytest.mark.asyncio
async def test_schedule_event() -> None:
    bus = Bus()
    received: list[ScheduleEvent] = []

    async def handler(event: ScheduleEvent) -> None:
        received.append(event)

    bus.subscribe(ScheduleEvent, handler)
    event = ScheduleEvent(schedule="daily")
    await bus.post(event)

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(bus.run(), timeout=0.1)

    assert received == [event]


@pytest.mark.asyncio
async def test_no_handler_for_type() -> None:
    bus = Bus()
    # No subscribers — should not raise
    await bus.post(make_inbound())

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(bus.run(), timeout=0.1)
