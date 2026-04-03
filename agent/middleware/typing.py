from __future__ import annotations

import asyncio

from agent.connectors import Connector, InboundEvent
from agent.middleware import Next

_TYPING_INTERVAL = 4.0  # Telegram drops the indicator after ~5s


class TypingMiddleware:
    def __init__(self, connectors: dict[str, Connector]) -> None:
        self._connectors = connectors

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        c = self._connectors.get(event.connector_name)
        if c is None:
            await next(event)
            return

        await c.send_typing(event.channel)

        async def _keep_typing() -> None:
            while True:
                await asyncio.sleep(_TYPING_INTERVAL)
                await c.send_typing(event.channel)  # type: ignore[union-attr]

        task = asyncio.create_task(_keep_typing())
        try:
            await next(event)
        finally:
            task.cancel()
