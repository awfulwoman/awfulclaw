from __future__ import annotations

from agent.connectors import Connector, InboundEvent, OutboundMessage
from agent.middleware import Next
from agent.store import Store


class SlashCommandMiddleware:
    def __init__(self, connector: Connector, store: Store) -> None:
        self._connector = connector
        self._store = store

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
            await self._connector.send(event.channel, OutboundMessage(text=reply))
            return

        if command == "/restart":
            await self._connector.send(event.channel, OutboundMessage(text="Restarting..."))
            return

        # Unknown slash command — pass through to the agent
        await next(event)
