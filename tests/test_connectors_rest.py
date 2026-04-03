from __future__ import annotations

import pytest
import httpx

from agent.connectors import InboundEvent, OutboundMessage
from agent.connectors.rest import RESTConnector


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
