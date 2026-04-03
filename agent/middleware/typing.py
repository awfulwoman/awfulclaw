from __future__ import annotations

from agent.connectors import Connector, InboundEvent
from agent.middleware import Next


class TypingMiddleware:
    def __init__(self, connectors: dict[str, Connector]) -> None:
        self._connectors = connectors

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        c = self._connectors.get(event.connector_name)
        if c:
            await c.send_typing(event.channel)
        await next(event)
