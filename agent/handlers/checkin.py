"""Ambient check-in handler — reads CHECKIN.md, invokes Claude, posts only if warranted."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agent.connectors import OutboundEvent, OutboundMessage

if TYPE_CHECKING:
    from agent.agent import Agent
    from agent.bus import Bus
    from agent.config import Settings
    from agent.store import Store

_LAST_CHECKIN_KEY = "last_checkin"

_SILENT_PATTERNS = (
    "nothing to report",
    "all clear",
    "no issues",
    "no action needed",
    "nothing warrants attention",
    "everything looks fine",
    "nothing requires attention",
    "silent",
    "heartbeat ok",
    "heartbeat: ok",
    "all systems",
    "no alerts",
    "no action required",
    "status: ok",
    "status: all clear",
)


def _warrants_attention(reply: str) -> bool:
    stripped = reply.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    return not any(lower == pat or lower.startswith(pat) for pat in _SILENT_PATTERNS)


class CheckinHandler:
    def __init__(self, agent: "Agent", bus: "Bus", store: "Store", settings: "Settings") -> None:
        self._agent = agent
        self._bus = bus
        self._store = store
        self._settings = settings

    async def run(self) -> None:
        """Check interval, invoke Claude with CHECKIN.md prompt, post if warranted."""
        last_str = await self._store.kv_get(_LAST_CHECKIN_KEY)
        now = time.time()

        if last_str is not None:
            elapsed = now - float(last_str)
            if elapsed < self._settings.checkin_interval:
                return

        checkin_path = self._settings.profile_path / "CHECKIN.md"
        prompt = checkin_path.read_text(encoding="utf-8")

        await self._store.kv_set(_LAST_CHECKIN_KEY, str(now))

        reply = await self._agent.invoke(prompt)

        if not _warrants_attention(reply):
            return

        channel = await self._store.kv_get("last_channel")
        sender = await self._store.kv_get("last_sender")
        if channel and sender:
            await self._bus.post(
                OutboundEvent(
                    channel=channel,
                    to=sender,
                    message=OutboundMessage(text=reply),
                )
            )
