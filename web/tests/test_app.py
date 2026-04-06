from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app  # noqa: E402

AGENT_BASE = "http://localhost:8080"


def _web_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _inject_agent_client():
    """Inject an AsyncClient into app.state so proxy handlers work without lifespan."""
    agent_client = httpx.AsyncClient(base_url=AGENT_BASE, timeout=130.0)
    app.state.client = agent_client
    yield
    del app.state._state["client"]


@respx.mock
@pytest.mark.anyio
async def test_proxy_chat_forwards_and_returns_reply():
    respx.post(f"{AGENT_BASE}/chat").mock(
        return_value=httpx.Response(200, json={"reply": "pong"})
    )
    async with _web_client() as c:
        r = await c.post("/proxy/chat", json={"message": "ping"})
    assert r.status_code == 200
    assert r.json() == {"reply": "pong"}


@respx.mock
@pytest.mark.anyio
async def test_proxy_status_forwards():
    respx.get(f"{AGENT_BASE}/api/status").mock(
        return_value=httpx.Response(200, json={"mcp": {}, "schedules": [], "kv": {}})
    )
    async with _web_client() as c:
        r = await c.get("/proxy/api/status")
    assert r.status_code == 200
    assert "mcp" in r.json()


@respx.mock
@pytest.mark.anyio
async def test_proxy_info_forwards():
    respx.get(f"{AGENT_BASE}/api/info/user").mock(
        return_value=httpx.Response(200, json={"content": "# User\nCharlie."})
    )
    async with _web_client() as c:
        r = await c.get("/proxy/api/info/user")
    assert r.status_code == 200
    assert r.json()["content"] == "# User\nCharlie."


@pytest.mark.anyio
async def test_index_serves_html():
    async with _web_client() as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.anyio
async def test_info_page_serves_html():
    async with _web_client() as c:
        r = await c.get("/info/personality")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
