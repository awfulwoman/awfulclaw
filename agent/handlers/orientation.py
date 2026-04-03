"""Orientation briefing — sent once on first startup to announce state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from agent.connectors import OutboundEvent, OutboundMessage

if TYPE_CHECKING:
    from agent.agent import Agent
    from agent.bus import Bus
    from agent.store import Store

_ORIENTATION_SENT_KEY = "orientation_sent"

_ORIENTATION_PROMPT = """
You are starting up for the first time. Write a brief orientation message to the user that includes:
1. A greeting confirming you are online.
2. A summary of the tools available to you (from the MCP servers listed below).
3. Any active schedules you are aware of (listed below).
4. Your current memory state: number of known facts and people.

Keep it concise and friendly.

Available MCP servers:
{mcp_servers}

Active schedules:
{schedules}

Known facts: {fact_count}
Known people: {people_count}
""".strip()


class OrientationHandler:
    def __init__(
        self,
        agent: "Agent",
        bus: "Bus",
        store: "Store",
        mcp_config_path: Path,
    ) -> None:
        self._agent = agent
        self._bus = bus
        self._store = store
        self._mcp_config_path = mcp_config_path

    async def run(self) -> None:
        """Send orientation message if not already sent."""
        already_sent = await self._store.kv_get(_ORIENTATION_SENT_KEY)
        if already_sent is not None:
            return

        mcp_servers = self._load_mcp_servers()
        schedules = await self._load_schedules()
        facts = await self._store.list_facts()
        people = await self._store.list_people()

        prompt = _ORIENTATION_PROMPT.format(
            mcp_servers=mcp_servers,
            schedules=schedules,
            fact_count=len(facts),
            people_count=len(people),
        )

        await self._store.kv_set(_ORIENTATION_SENT_KEY, "1")

        reply = await self._agent.invoke(prompt)

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

    def _load_mcp_servers(self) -> str:
        try:
            data = json.loads(self._mcp_config_path.read_text(encoding="utf-8"))
            servers = list(data.get("mcpServers", {}).keys())
            return ", ".join(servers) if servers else "none configured"
        except Exception:
            return "unavailable"

    async def _load_schedules(self) -> str:
        try:
            schedules = await self._store.list_schedules()
            if not schedules:
                return "none"
            return "; ".join(
                f"{s.name} ({s.cron})" for s in schedules
            )
        except Exception:
            return "unavailable"
