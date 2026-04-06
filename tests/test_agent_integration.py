from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from agent.bus import Bus
from agent.connectors import InboundEvent, OutboundEvent
from agent.connectors.rest import RESTConnector
from agent.middleware.invoke import InvokeMiddleware
from agent.middleware.location import LocationMiddleware
from agent.middleware.rate_limit import RateLimitMiddleware
from agent.middleware.secret import SecretCaptureMiddleware
from agent.middleware.slash import SlashCommandMiddleware
from agent.middleware.typing import TypingMiddleware
from agent.pipeline import Pipeline
from agent.store import Store


@pytest.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


async def _make_full_pipeline(
    connector: RESTConnector, store: Store, agent: AsyncMock, bus: Bus
) -> Pipeline:
    return Pipeline([
        RateLimitMiddleware(),
        SecretCaptureMiddleware(store),
        LocationMiddleware(store),
        SlashCommandMiddleware({"rest": connector}, store),
        TypingMiddleware({"rest": connector}),
        InvokeMiddleware(agent, bus),
    ])


@pytest.mark.asyncio
async def test_rest_post_gets_reply() -> None:
    connector = RESTConnector(port=8080)
    bus = Bus()

    agent = AsyncMock()
    agent.reply = AsyncMock(return_value="pong")

    pipeline = Pipeline([InvokeMiddleware(agent, bus)])

    async def handle_outbound(event: OutboundEvent) -> None:
        await connector.send(event.to, event.message)

    bus.subscribe(InboundEvent, pipeline.run)
    bus.subscribe(OutboundEvent, handle_outbound)

    # Wire on_message without calling start() (avoids uvicorn)
    connector._on_message = bus.post  # type: ignore[assignment]

    bus_task = asyncio.create_task(bus.run())
    try:
        transport = httpx.ASGITransport(app=connector.app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/chat", json={"message": "ping"})

        assert resp.status_code == 200
        assert resp.json()["reply"] == "pong"
    finally:
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_slash_command_returns_response_without_invoking_agent(
    store: Store,
) -> None:
    """Slash command is handled by SlashCommandMiddleware; agent is never called."""
    connector = RESTConnector(port=8081)
    bus = Bus()

    agent = AsyncMock()
    agent.reply = AsyncMock(return_value="should not appear")

    pipeline = await _make_full_pipeline(connector, store, agent, bus)

    async def handle_outbound(event: OutboundEvent) -> None:
        await connector.send(event.to, event.message)

    bus.subscribe(InboundEvent, pipeline.run)
    bus.subscribe(OutboundEvent, handle_outbound)
    connector._on_message = bus.post  # type: ignore[assignment]

    bus_task = asyncio.create_task(bus.run())
    try:
        transport = httpx.ASGITransport(app=connector.app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/chat", json={"message": "/schedules"})

        assert resp.status_code == 200
        assert "schedule" in resp.json()["reply"].lower()
        agent.reply.assert_not_called()
    finally:
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_normal_message_reaches_agent(store: Store) -> None:
    """Normal messages pass through all middleware and reach InvokeMiddleware."""
    connector = RESTConnector(port=8082)
    bus = Bus()

    agent = AsyncMock()
    agent.reply = AsyncMock(return_value="hello back")

    pipeline = await _make_full_pipeline(connector, store, agent, bus)

    async def handle_outbound(event: OutboundEvent) -> None:
        await connector.send(event.to, event.message)

    bus.subscribe(InboundEvent, pipeline.run)
    bus.subscribe(OutboundEvent, handle_outbound)
    connector._on_message = bus.post  # type: ignore[assignment]

    bus_task = asyncio.create_task(bus.run())
    try:
        transport = httpx.ASGITransport(app=connector.app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/chat", json={"message": "hello"})

        assert resp.status_code == 200
        assert resp.json()["reply"] == "hello back"
        agent.reply.assert_called_once()
    finally:
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
