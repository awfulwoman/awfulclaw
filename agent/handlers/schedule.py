from __future__ import annotations

from typing import TYPE_CHECKING

from agent.connectors import OutboundEvent, OutboundMessage

if TYPE_CHECKING:
    from agent.agent import Agent
    from agent.bus import Bus, ScheduleEvent
    from agent.store import Store


class ScheduleHandler:
    def __init__(self, agent: "Agent", bus: "Bus", store: "Store") -> None:
        self._agent = agent
        self._bus = bus
        self._store = store

    async def handle(self, event: "ScheduleEvent") -> None:
        schedule = event.schedule
        reply = await self._agent.invoke(schedule.prompt)

        if not schedule.silent:
            channel = await self._store.kv_get("last_channel")
            sender = await self._store.kv_get("last_sender")
            connector_name = await self._store.kv_get("last_connector") or ""
            if channel and sender:
                await self._bus.post(
                    OutboundEvent(
                        channel=channel,
                        to=sender,
                        message=OutboundMessage(text=reply),
                        connector_name=connector_name,
                    )
                )
