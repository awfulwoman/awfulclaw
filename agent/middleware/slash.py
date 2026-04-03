from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable

from agent.connectors import Connector, InboundEvent, OutboundMessage
from agent.middleware import Next
from agent.store import Store


class SlashCommandMiddleware:
    def __init__(
        self,
        connectors: dict[str, Connector],
        store: Store,
        restart_fn: Callable[[], None] | None = None,
    ) -> None:
        self._connectors = connectors
        self._store = store
        self._restart_fn = restart_fn or (lambda: os.kill(os.getpid(), signal.SIGTERM))

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        text = event.message.text.strip()

        if not text.startswith("/"):
            await next(event)
            return

        command = text.split()[0].lower()

        if command == "/schedules":
            schedules = await self._store.list_schedules()
            if schedules:
                lines = [f"- {s.name} ({s.cron or s.fire_at or 'no time'})" for s in schedules]
                reply = "Schedules:\n" + "\n".join(lines)
            else:
                reply = "No schedules."
            c = self._connectors.get(event.connector_name)
            if c:
                await c.send(event.channel, OutboundMessage(text=reply))
            return

        if command == "/restart":
            c = self._connectors.get(event.connector_name)
            if c:
                await c.send(event.channel, OutboundMessage(text="Restarting..."))
            asyncio.get_running_loop().call_later(0.1, self._restart_fn)
            return

        # Unknown slash command — pass through to the agent
        await next(event)
