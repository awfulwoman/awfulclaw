from __future__ import annotations

import time
from collections import defaultdict

from agent.connectors import InboundEvent
from agent.middleware import Next


class RateLimitMiddleware:
    def __init__(self, max_count: int = 10, window_seconds: float = 60.0) -> None:
        self._max_count = max_count
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = defaultdict(list)

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        sender = event.message.sender
        now = time.monotonic()
        cutoff = now - self._window

        timestamps = self._timestamps[sender]
        # Drop timestamps outside the window
        self._timestamps[sender] = [t for t in timestamps if t >= cutoff]

        if len(self._timestamps[sender]) >= self._max_count:
            return  # short-circuit

        self._timestamps[sender].append(now)
        await next(event)
