from __future__ import annotations

from typing import Any, Callable, Coroutine, Protocol

from agent.connectors import InboundEvent

Next = Callable[[InboundEvent], Coroutine[Any, Any, None]]


class Middleware(Protocol):
    async def __call__(self, event: InboundEvent, next: Next) -> None: ...
