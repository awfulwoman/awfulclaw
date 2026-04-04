from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.connectors import InboundEvent, OutboundMessage
from agent.connectors.telegram import TelegramConnector


def make_voice_update(
    update_id: int,
    chat_id: int,
    file_id: str = "FILEID123",
    user_id: int = 99,
    username: str = "alice",
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "first_name": username, "username": username},
            "voice": {"file_id": file_id, "duration": 5, "mime_type": "audio/ogg"},
        },
    }


def make_store(offset: str | None = None) -> MagicMock:
    store = MagicMock()
    store.kv_get = AsyncMock(return_value=offset)
    store.kv_set = AsyncMock()
    return store


def make_mock_client(get_side_effect: list) -> MagicMock:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=get_side_effect)
    mock_client.post = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def make_getfile_resp(file_path: str = "voice/file.ogg") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"result": {"file_path": file_path}})
    return resp


def make_download_resp(content: bytes = b"fake-ogg-data") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    return resp


def make_poll_resp(updates: dict) -> MagicMock:
    resp = MagicMock()
    resp.json = MagicMock(return_value=updates)
    return resp


@pytest.mark.asyncio
async def test_voice_message_transcribed() -> None:
    store = make_store()
    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock(return_value="Hello from voice")

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store, transcriber=transcriber
    )

    updates = {"result": [make_voice_update(1, 100, file_id="FILE123")]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)
        connector._running = False

    mock_client = make_mock_client([
        make_poll_resp(updates),   # getUpdates
        make_getfile_resp(),       # getFile
        make_download_resp(),      # file download
    ])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 1
    assert received[0].message.text == "[Voice]: Hello from voice"
    transcriber.transcribe.assert_called_once_with(b"fake-ogg-data", "audio/ogg")


@pytest.mark.asyncio
async def test_voice_transcription_failure_sends_error_and_skips() -> None:
    store = make_store()

    async def stop_after_set(key: str, value: str) -> None:
        connector._running = False

    store.kv_set = AsyncMock(side_effect=stop_after_set)

    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock(side_effect=RuntimeError("model exploded"))

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store, transcriber=transcriber
    )

    updates = {"result": [make_voice_update(1, 100)]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)

    mock_client = make_mock_client([
        make_poll_resp(updates),
        make_getfile_resp(),
        make_download_resp(),
    ])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 0
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["text"] == "Sorry, I couldn't transcribe that voice note."


@pytest.mark.asyncio
async def test_voice_download_failure_sends_error_and_skips() -> None:
    store = make_store()

    async def stop_after_set(key: str, value: str) -> None:
        connector._running = False

    store.kv_set = AsyncMock(side_effect=stop_after_set)

    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock()

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store, transcriber=transcriber
    )

    updates = {"result": [make_voice_update(1, 100)]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)

    failing_getfile = MagicMock()
    failing_getfile.raise_for_status = MagicMock(side_effect=Exception("getFile failed"))

    mock_client = make_mock_client([
        make_poll_resp(updates),
        failing_getfile,
    ])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 0
    transcriber.transcribe.assert_not_called()
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["text"] == "Sorry, I couldn't transcribe that voice note."


@pytest.mark.asyncio
async def test_voice_without_transcriber_silently_skipped() -> None:
    store = make_store()

    async def stop_after_set(key: str, value: str) -> None:
        connector._running = False

    store.kv_set = AsyncMock(side_effect=stop_after_set)

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store
    )

    updates = {"result": [make_voice_update(1, 100)]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)

    mock_client = make_mock_client([make_poll_resp(updates)])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 0
    mock_client.post.assert_not_called()
