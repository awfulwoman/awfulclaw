from __future__ import annotations

from typing import Any, Coroutine, Callable, Protocol

from agent.connectors import InboundEvent, OutboundEvent, OutboundMessage
from agent.middleware import Next


class AgentProtocol(Protocol):
    async def reply(self, event: InboundEvent) -> str: ...


class BusProtocol(Protocol):
    async def post(self, event: OutboundEvent) -> None: ...  # type: ignore[misc]


class StoreProtocol(Protocol):
    async def kv_set(self, key: str, value: str) -> None: ...


class InvokeMiddleware:
    def __init__(self, agent: AgentProtocol, bus: BusProtocol, store: StoreProtocol | None = None) -> None:
        self._agent = agent
        self._bus = bus
        self._store = store

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        if self._store is not None:
            await self._store.kv_set("last_channel", event.channel)
            await self._store.kv_set("last_sender", event.message.sender)
        reply_text = await self._agent.reply(event)
        outbound = OutboundEvent(
            channel=event.channel,
            to=event.message.sender,
            message=OutboundMessage(text=reply_text),
        )
        await self._bus.post(outbound)
