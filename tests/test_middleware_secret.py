from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.connectors import InboundEvent, Message
from agent.middleware.secret import SecretCaptureMiddleware
from agent.store import Store


@pytest.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


def _event(text: str) -> InboundEvent:
    return InboundEvent(
        channel="ch1",
        message=Message(text=text, sender="u1", sender_name="User"),
        connector_name="test",
    )


async def test_normal_message_passes_through(store: Store) -> None:
    mw = SecretCaptureMiddleware(store)
    next_fn = AsyncMock()

    await mw(_event("hello"), next_fn)

    next_fn.assert_called_once()


async def test_pending_key_intercepts_message(store: Store) -> None:
    await store.kv_set("pending_secret_key", "MY_API_KEY")

    mw = SecretCaptureMiddleware(store)
    next_fn = AsyncMock()

    await mw(_event("supersecret123"), next_fn)

    # Short-circuited — next not called
    next_fn.assert_not_called()

    # Pending key cleared
    assert await store.kv_get("pending_secret_key") is None

    # Secret stored for env_manager
    captured = await store.kv_get("captured_secret:MY_API_KEY")
    assert captured == "supersecret123"
