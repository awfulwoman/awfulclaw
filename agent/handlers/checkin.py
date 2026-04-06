"""Ambient check-in handler — reads CHECKIN.md, invokes Claude, posts only if warranted."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from agent.connectors import OutboundEvent, OutboundMessage

if TYPE_CHECKING:
    from agent.agent import Agent
    from agent.bus import Bus
    from agent.config import Settings
    from agent.store import Store

_LAST_CHECKIN_KEY = "last_checkin"
_TRIAGE_KV_KEY = "email_triage"

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
        """Check interval, consume triage results, invoke Claude only if needed."""
        last_str = await self._store.kv_get(_LAST_CHECKIN_KEY)
        now = time.time()

        if last_str is not None:
            elapsed = now - float(last_str)
            if elapsed < self._settings.checkin_interval:
                # Also trigger on idle: if no messages received since last check-in
                if elapsed < self._settings.idle_interval:
                    return
                last_msg_str = await self._store.kv_get("last_message_time")
                if last_msg_str is not None and float(last_msg_str) >= float(last_str):
                    return  # messages received since last check-in; not idle

        await self._store.kv_set(_LAST_CHECKIN_KEY, str(now))

        # Consume triage results accumulated since last check-in
        triage_raw = await self._store.kv_get(_TRIAGE_KV_KEY)
        triage = json.loads(triage_raw) if triage_raw else {}
        if triage:
            await self._store.kv_delete(_TRIAGE_KV_KEY)

        escalated = triage.get("escalate", [])
        routine = triage.get("routine", [])
        newsletters = triage.get("newsletters", [])

        reply: str | None = None

        if escalated:
            # Build a focused prompt for the external model with only escalated items
            lines = ["Some emails need your attention:"]
            for item in escalated:
                lines.append(f"- From {item.get('from', '?')}: {item.get('summary', item.get('subject', '?'))}")
            if routine:
                lines.append(f"\nAlso {len(routine)} routine email(s): " + "; ".join(routine[:5]))
            if newsletters:
                lines.append(f"And {len(newsletters)} newsletter(s) filtered.")
            prompt = "\n".join(lines)
            reply = await self._agent.invoke(prompt)
        elif triage:
            # Only routine/newsletter items — no model call needed
            return
        else:
            # No triage results — full CHECKIN.md check
            checkin_path = self._settings.profile_path / "CHECKIN.md"
            prompt = checkin_path.read_text(encoding="utf-8")
            reply = await self._agent.invoke(prompt)

        if reply is None or not _warrants_attention(reply):
            return

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
