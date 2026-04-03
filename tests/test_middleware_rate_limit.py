from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from agent.connectors import InboundEvent, Message
from agent.middleware import Next
from agent.middleware.rate_limit import RateLimitMiddleware


def make_event(sender: str = "user1") -> InboundEvent:
    return InboundEvent(
        channel="chan",
        message=Message(text="hi", sender=sender, sender_name="Alice"),
        connector_name="test",
    )


@pytest.mark.asyncio
async def test_under_limit_passes_through() -> None:
    mw = RateLimitMiddleware(max_count=3, window_seconds=60.0)
    next_fn: Next = AsyncMock()

    for _ in range(3):
        await mw(make_event(), next_fn)

    assert next_fn.call_count == 3


@pytest.mark.asyncio
async def test_over_limit_blocks() -> None:
    mw = RateLimitMiddleware(max_count=3, window_seconds=60.0)
    next_fn: Next = AsyncMock()

    for _ in range(5):
        await mw(make_event(), next_fn)

    assert next_fn.call_count == 3


@pytest.mark.asyncio
async def test_different_senders_tracked_independently() -> None:
    mw = RateLimitMiddleware(max_count=2, window_seconds=60.0)
    next_fn: Next = AsyncMock()

    for _ in range(3):
        await mw(make_event("alice"), next_fn)
    for _ in range(3):
        await mw(make_event("bob"), next_fn)

    assert next_fn.call_count == 4  # 2 + 2


@pytest.mark.asyncio
async def test_old_timestamps_evicted() -> None:
    import time

    mw = RateLimitMiddleware(max_count=2, window_seconds=1.0)
    next_fn: Next = AsyncMock()

    # Use up the limit
    await mw(make_event(), next_fn)
    await mw(make_event(), next_fn)

    # Manually backdate the timestamps so they expire
    mw._timestamps["user1"] = [time.monotonic() - 2.0, time.monotonic() - 2.0]

    # Now should pass through again
    await mw(make_event(), next_fn)

    assert next_fn.call_count == 3
