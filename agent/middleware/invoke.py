from __future__ import annotations

from typing import Any, Coroutine, Callable, Protocol

from agent.connectors import InboundEvent, OutboundEvent, OutboundMessage
from agent.middleware import Next


class AgentProtocol(Protocol):
    async def reply(self, event: InboundEvent) -> str: ...


class BusProtocol(Protocol):
    async def post(self, event: OutboundEvent) -> None: ...  # type: ignore[misc]


class InvokeMiddleware:
    def __init__(self, agent: AgentProtocol, bus: BusProtocol) -> None:
        self._agent = agent
        self._bus = bus

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        reply_text = await self._agent.reply(event)
        outbound = OutboundEvent(
            channel=event.channel,
            to=event.message.sender,
            message=OutboundMessage(text=reply_text),
        )
        await self._bus.post(outbound)
