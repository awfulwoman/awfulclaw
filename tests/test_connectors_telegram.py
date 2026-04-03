from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.connectors import InboundEvent, OutboundMessage
from agent.connectors.telegram import TelegramConnector


def make_update(update_id: int, chat_id: int, text: str, user_id: int = 99,
                username: str = "alice", chat_type: str = "private") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": user_id, "first_name": username, "username": username},
            "text": text,
        },
    }


def make_store(offset: str | None = None) -> MagicMock:
    store = MagicMock()
    store.kv_get = AsyncMock(return_value=offset)
    store.kv_set = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_polling_fires_on_message() -> None:
    store = make_store()
    connector = TelegramConnector(token="tok", allowed_chat_ids=[100], store=store)

    updates = {"result": [make_update(1, 100, "hello")]}
    empty = {"result": []}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)
        connector._running = False

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(side_effect=[updates, empty])

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 1
    assert received[0].channel == "100"
    assert received[0].message.text == "hello"
    assert received[0].connector_name == "telegram"


@pytest.mark.asyncio
async def test_batching_combines_messages() -> None:
    store = make_store()
    connector = TelegramConnector(token="tok", allowed_chat_ids=[100], store=store)

    updates = {
        "result": [
            make_update(1, 100, "first"),
            make_update(2, 100, "second"),
        ]
    }

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)
        connector._running = False

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value=updates)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 1
    assert "first" in received[0].message.text
    assert "second" in received[0].message.text


@pytest.mark.asyncio
async def test_offset_persisted() -> None:
    store = make_store(offset="5")
    connector = TelegramConnector(token="tok", allowed_chat_ids=[100], store=store)

    updates = {"result": [make_update(10, 100, "hi")]}

    async def on_message(event: InboundEvent) -> None:
        connector._running = False

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value=updates)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    # getUpdates should use offset=5 (from store), new offset should be 11
    call_params = mock_client.get.call_args[1]["params"]
    assert call_params["offset"] == 5
    store.kv_set.assert_called_with("telegram_offset", "11")


@pytest.mark.asyncio
async def test_untrusted_content_framing() -> None:
    store = make_store()
    owner_id = 42
    connector = TelegramConnector(token="tok", allowed_chat_ids=[200], store=store, owner_id=owner_id)

    updates = {
        "result": [
            make_update(1, 200, "stranger message", user_id=99, username="stranger", chat_type="group"),
        ]
    }

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)
        connector._running = False

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value=updates)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 1
    text = received[0].message.text
    assert '<untrusted-content source="chat-user" from="stranger">' in text
    assert "stranger message" in text


@pytest.mark.asyncio
async def test_owner_not_framed_in_group() -> None:
    store = make_store()
    owner_id = 42
    connector = TelegramConnector(token="tok", allowed_chat_ids=[200], store=store, owner_id=owner_id)

    updates = {
        "result": [
            make_update(1, 200, "owner says hi", user_id=42, username="owner", chat_type="group"),
        ]
    }

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)
        connector._running = False

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value=updates)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    text = received[0].message.text
    assert "<untrusted-content" not in text
    assert "owner says hi" in text


@pytest.mark.asyncio
async def test_disallowed_chat_ids_filtered() -> None:
    store = make_store()
    connector = TelegramConnector(token="tok", allowed_chat_ids=[100], store=store)

    updates = {"result": [make_update(1, 999, "sneaky")]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)

    # Stop after first kv_set (offset persistence happens after poll)
    async def stop_after_set(key: str, value: str) -> None:
        connector._running = False

    store.kv_set = AsyncMock(side_effect=stop_after_set)

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value=updates)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 0


@pytest.mark.asyncio
async def test_verify_token() -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"ok": True, "result": {"id": 1, "username": "testbot"}})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        result = await TelegramConnector.verify_token("mytoken")

    assert result["ok"] is True
