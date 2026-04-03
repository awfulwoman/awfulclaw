from __future__ import annotations

from agent.connectors import InboundEvent
from agent.middleware import Middleware, Next


class Pipeline:
    def __init__(self, middleware: list[Middleware]) -> None:
        self._middleware = middleware

    async def run(self, event: InboundEvent) -> None:
        async def noop(event: InboundEvent) -> None:
            pass

        chain: Next = noop
        for mw in reversed(self._middleware):
            # Capture mw and current chain in closure
            _mw = mw
            _next = chain

            async def make_next(ev: InboundEvent, mw: Middleware = _mw, n: Next = _next) -> None:
                await mw(ev, n)

            chain = make_next

        await chain(event)
