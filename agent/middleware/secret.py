from __future__ import annotations

from agent.connectors import InboundEvent
from agent.middleware import Next
from agent.store import Store

_PENDING_KEY = "pending_secret_key"


class SecretCaptureMiddleware:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        pending = await self._store.kv_get(_PENDING_KEY)
        if pending is None:
            await next(event)
            return

        # Capture the message as the secret value; clear the pending marker
        env_key = pending
        secret_value = event.message.text
        await self._store.kv_delete(_PENDING_KEY)

        # Store for env_manager to persist on next write cycle
        await self._store.kv_set(f"captured_secret:{env_key}", secret_value)
        # Short-circuit — do not pass to next middleware
