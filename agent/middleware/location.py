from __future__ import annotations

import re
from dataclasses import replace

from agent.connectors import InboundEvent, Message
from agent.middleware import Next
from agent.store import Store

_LOCATION_RE = re.compile(r"\[Location:\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\]")


class LocationMiddleware:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        m = _LOCATION_RE.search(event.message.text)
        if m is None:
            await next(event)
            return

        lat, lon = m.group(1), m.group(2)
        await self._store.kv_set("user_lat", lat)
        await self._store.kv_set("user_lon", lon)

        cleaned = _LOCATION_RE.sub("", event.message.text).strip()
        if not cleaned:
            return  # short-circuit

        new_message = replace(event.message, text=cleaned)
        new_event = replace(event, message=new_message)
        await next(new_event)
