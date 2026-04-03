from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, TypeVar

from agent.connectors import InboundEvent, OutboundEvent


@dataclass
class ScheduleEvent:
    schedule: str


Event = InboundEvent | OutboundEvent | ScheduleEvent
Handler = Callable[[Any], Coroutine[Any, Any, None]]

E = TypeVar("E", InboundEvent, OutboundEvent, ScheduleEvent)


class Bus:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers: dict[type, list[Handler]] = {}

    async def post(self, event: Event) -> None:
        await self._queue.put(event)

    def subscribe(self, event_type: type[E], handler: Callable[[E], Coroutine[Any, Any, None]]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)  # type: ignore[arg-type]

    async def run(self) -> None:
        while True:
            event = await self._queue.get()
            handlers = self._subscribers.get(type(event), [])
            for handler in handlers:
                await handler(event)
            self._queue.task_done()
