from __future__ import annotations

import pytest
import httpx
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent.connectors import InboundEvent, OutboundMessage
from agent.connectors.rest import RESTConnector
from agent.store import Store
from agent.mcp import MCPClient


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    (tmp_path / "PERSONALITY.md").write_text("# Personality\nI am helpful.")
    (tmp_path / "PROTOCOLS.md").write_text("# Protocols\nBe concise.")
    (tmp_path / "USER.md").write_text("# User\nCharlie.")
    (tmp_path / "CHECKIN.md").write_text("# Check-in\nCheck daily.")
    return tmp_path


@pytest.mark.asyncio
async def test_post_chat_returns_reply() -> None:
    connector = RESTConnector()

    async def on_message(event: InboundEvent) -> None:
        await connector.send(event.message.sender, OutboundMessage(text="hello back"))

    connector._on_message = on_message

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=connector.app), base_url="http://test"
    ) as client:
        r = await client.post("/chat", json={"message": "hello"})

    assert r.status_code == 200
    assert r.json() == {"reply": "hello back"}


@pytest.mark.asyncio
async def test_chat_uses_primary_channel() -> None:
    connector = RESTConnector()
    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)
        assert event.reply_to is not None
        await connector.send(event.reply_to, OutboundMessage(text="ok"))

    connector._on_message = on_message

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=connector.app), base_url="http://test"
    ) as client:
        r = await client.post("/chat", json={"message": "hi"})

    assert r.status_code == 200
    assert r.json() == {"reply": "ok"}
    assert received[0].channel == "primary"
    assert received[0].reply_to is not None


@pytest.mark.asyncio
async def test_send_typing_is_noop() -> None:
    connector = RESTConnector()
    await connector.send_typing("whoever")  # should not raise


@pytest.mark.asyncio
async def test_send_resolves_pending_future() -> None:
    import asyncio

    connector = RESTConnector()
    future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
    connector._pending["chan1"] = future

    await connector.send("chan1", OutboundMessage(text="done"))

    assert future.result() == "done"
    assert "chan1" not in connector._pending


@pytest.mark.asyncio
async def test_send_ignores_unknown_channel() -> None:
    connector = RESTConnector()
    # Should not raise even if channel not pending
    await connector.send("unknown", OutboundMessage(text="hi"))


@pytest.mark.asyncio
async def test_multiple_requests_independent() -> None:
    connector = RESTConnector()

    async def on_message(event: InboundEvent) -> None:
        reply = f"echo:{event.message.text}"
        await connector.send(event.message.sender, OutboundMessage(text=reply))

    connector._on_message = on_message

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=connector.app), base_url="http://test"
    ) as client:
        r1 = await client.post("/chat", json={"message": "one"})
        r2 = await client.post("/chat", json={"message": "two"})

    assert r1.json() == {"reply": "echo:one"}
    assert r2.json() == {"reply": "echo:two"}


@pytest.mark.asyncio
async def test_get_status_returns_mcp_schedules_kv() -> None:
    mock_store = AsyncMock(spec=Store)
    mock_store.list_schedules.return_value = []
    mock_store.kv_list.return_value = [
        ("timezone", "Europe/London"),
        ("captured_secret:x", "hidden"),
    ]

    mock_mcp = MagicMock(spec=MCPClient)
    mock_mcp.server_status.return_value = {"memory": True, "weather": False}

    connector = RESTConnector(store=mock_store, mcp=mock_mcp)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=connector.app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")

    assert r.status_code == 200
    data = r.json()
    assert data["mcp"] == {"memory": True, "weather": False}
    assert "timezone" in data["kv"]
    assert "captured_secret:x" not in data["kv"]


@pytest.mark.asyncio
async def test_get_info_returns_profile_content(profile_dir: Path) -> None:
    connector = RESTConnector(profile_path=profile_dir)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=connector.app), base_url="http://test"
    ) as client:
        r = await client.get("/api/info/personality")

    assert r.status_code == 200
    assert "Personality" in r.json()["content"]


@pytest.mark.asyncio
async def test_get_info_unknown_name_returns_404(profile_dir: Path) -> None:
    connector = RESTConnector(profile_path=profile_dir)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=connector.app), base_url="http://test"
    ) as client:
        r = await client.get("/api/info/unknown")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_info_no_profile_path_returns_404() -> None:
    connector = RESTConnector()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=connector.app), base_url="http://test"
    ) as client:
        r = await client.get("/api/info/personality")

    assert r.status_code == 404
