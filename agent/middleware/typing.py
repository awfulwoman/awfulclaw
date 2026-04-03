from __future__ import annotations

from agent.connectors import Connector, InboundEvent
from agent.middleware import Next


class TypingMiddleware:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        await self._connector.send_typing(event.channel)
        await next(event)
