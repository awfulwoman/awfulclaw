from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.connectors import InboundEvent, Message
from agent.middleware import Next
from agent.middleware.location import LocationMiddleware


def make_event(text: str) -> InboundEvent:
    return InboundEvent(
        channel="chan",
        message=Message(text=text, sender="user1", sender_name="Alice"),
        connector_name="test",
    )


def make_store() -> MagicMock:
    store = MagicMock()
    store.kv_set = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_no_location_passes_through() -> None:
    store = make_store()
    mw = LocationMiddleware(store)
    next_fn: Next = AsyncMock()

    await mw(make_event("hello world"), next_fn)

    next_fn.assert_called_once()
    store.kv_set.assert_not_called()
    called_event: InboundEvent = next_fn.call_args[0][0]
    assert called_event.message.text == "hello world"


@pytest.mark.asyncio
async def test_location_only_short_circuits() -> None:
    store = make_store()
    mw = LocationMiddleware(store)
    next_fn: Next = AsyncMock()

    await mw(make_event("[Location: 48.8566, 2.3522]"), next_fn)

    next_fn.assert_not_called()
    store.kv_set.assert_any_call("user_lat", "48.8566")
    store.kv_set.assert_any_call("user_lon", "2.3522")


@pytest.mark.asyncio
async def test_location_with_text_passes_cleaned() -> None:
    store = make_store()
    mw = LocationMiddleware(store)
    next_fn: Next = AsyncMock()

    await mw(make_event("Check this [Location: 51.5074, -0.1278] out"), next_fn)

    next_fn.assert_called_once()
    store.kv_set.assert_any_call("user_lat", "51.5074")
    store.kv_set.assert_any_call("user_lon", "-0.1278")
    called_event: InboundEvent = next_fn.call_args[0][0]
    assert called_event.message.text == "Check this  out".strip() or "Location" not in called_event.message.text


@pytest.mark.asyncio
async def test_location_with_text_cleaned_correctly() -> None:
    store = make_store()
    mw = LocationMiddleware(store)
    next_fn: Next = AsyncMock()

    await mw(make_event("[Location: 40.7128, -74.0060] Hello"), next_fn)

    next_fn.assert_called_once()
    called_event: InboundEvent = next_fn.call_args[0][0]
    assert called_event.message.text == "Hello"
    assert called_event.channel == "chan"
