from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from agent.bus import Bus
from agent.connectors import InboundEvent, OutboundEvent
from agent.connectors.rest import RESTConnector
from agent.middleware.invoke import InvokeMiddleware
from agent.pipeline import Pipeline


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
