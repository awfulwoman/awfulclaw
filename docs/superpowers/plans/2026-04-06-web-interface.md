# Web Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browser-based chat + status dashboard to awfulclaw via a separate, Docker-deployable Python web app that proxies to the agent's REST API.

**Architecture:** A standalone Starlette app in `web/` serves static pages and proxies all calls to the agent REST API (configured via `AGENT_URL` env var). The browser UI uses browser-native web components (Custom Elements + Shadow DOM) with no build step. The agent gains two new read-only endpoints and its bind address is tightened to `127.0.0.1`.

**Tech Stack:** Python 3.12, Starlette, uvicorn, httpx (proxy), vanilla JS web components, Docker + docker-compose.

---

## File Map

**Agent — modified:**
- `agent/store.py` — add `kv_list()` method
- `agent/mcp/__init__.py` — add `server_status()` method
- `agent/connectors/rest.py` — add `/api/status` + `/api/info/{name}` endpoints; accept `store`, `mcp`, `profile_path` in constructor; bind to `127.0.0.1`
- `agent/main.py` — pass `store`, `mcp`, `profile_path` to `RESTConnector`

**Agent — tests modified:**
- `tests/test_store_crud.py` — add `kv_list` test
- `tests/test_mcp_client.py` — add `server_status` test
- `tests/test_connectors_rest.py` — add endpoint tests

**Web app — new:**
- `web/app.py` — Starlette app with proxy routes + page routes
- `web/requirements.txt`
- `web/Dockerfile`
- `web/docker-compose.yml`
- `web/pages/index.html` — chat + sidebar page
- `web/pages/info.html` — profile content page
- `web/static/style.css` — global layout styles
- `web/static/components/agent-chat.js` — `<agent-chat>` web component
- `web/static/components/agent-sidebar.js` — `<agent-sidebar>` web component
- `web/static/components/profile-viewer.js` — `<profile-viewer>` web component
- `web/tests/__init__.py`
- `web/tests/test_app.py` — proxy route tests

---

## Task 1: Add `kv_list()` to Store

**Files:**
- Modify: `agent/store.py`
- Test: `tests/test_store_crud.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_store_crud.py` and add this test. (Check the existing fixture name — there is a `store` fixture defined in this file or conftest that provides a `Store` instance.)

```python
@pytest.mark.asyncio
async def test_kv_list(store: Store) -> None:
    await store.kv_set("alpha", "one")
    await store.kv_set("beta", "two")
    result = await store.kv_list()
    assert ("alpha", "one") in result
    assert ("beta", "two") in result
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/test_store_crud.py::test_kv_list -v
```

Expected: `AttributeError: 'Store' object has no attribute 'kv_list'`

- [ ] **Step 3: Add `kv_list()` to Store**

In `agent/store.py`, in the `# --- kv ---` section (after `kv_delete`), add:

```python
async def kv_list(self) -> list[tuple[str, str]]:
    cursor = await self._db.execute("SELECT key, value FROM kv ORDER BY key")
    rows = await cursor.fetchall()
    return [(r[0], r[1]) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

```
uv run pytest tests/test_store_crud.py::test_kv_list -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/store.py tests/test_store_crud.py
git commit -m "feat: add kv_list() to Store"
```

---

## Task 2: Add `server_status()` to MCPClient

**Files:**
- Modify: `agent/mcp/__init__.py`
- Test: `tests/test_mcp_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_client.py`:

```python
import json
from pathlib import Path
from agent.mcp import MCPClient


def test_server_status_connected_and_disconnected(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"memory": {}, "weather": {}}}))

    client = MCPClient()
    client._config_path = config
    # Simulate only 'memory' being connected
    client._server_sessions["memory"] = object()  # type: ignore[assignment]

    status = client.server_status()
    assert status == {"memory": True, "weather": False}


def test_server_status_no_config() -> None:
    client = MCPClient()
    assert client.server_status() == {}


def test_server_status_excludes_excluded_servers(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"memory": {}, "eventkit": {}}}))

    client = MCPClient()
    client._config_path = config
    client._exclude = frozenset({"eventkit"})
    client._server_sessions["memory"] = object()  # type: ignore[assignment]

    status = client.server_status()
    assert "eventkit" not in status
    assert status["memory"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_mcp_client.py::test_server_status_connected_and_disconnected tests/test_mcp_client.py::test_server_status_no_config tests/test_mcp_client.py::test_server_status_excludes_excluded_servers -v
```

Expected: `AttributeError: 'MCPClient' object has no attribute 'server_status'`

- [ ] **Step 3: Add `server_status()` to MCPClient**

In `agent/mcp/__init__.py`, add this method after `list_tools()`:

```python
def server_status(self) -> dict[str, bool]:
    """Return {name: connected} for all configured servers not in _exclude."""
    if self._config_path is None:
        return {}
    try:
        raw: dict[str, Any] = json.loads(self._config_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {name: True for name in self._server_sessions}
    servers = raw.get("mcpServers", raw)
    return {
        name: name in self._server_sessions
        for name in servers
        if name not in self._exclude
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_mcp_client.py::test_server_status_connected_and_disconnected tests/test_mcp_client.py::test_server_status_no_config tests/test_mcp_client.py::test_server_status_excludes_excluded_servers -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add agent/mcp/__init__.py tests/test_mcp_client.py
git commit -m "feat: add server_status() to MCPClient"
```

---

## Task 3: Extend RESTConnector with `/api/status` and `/api/info/{name}`

**Files:**
- Modify: `agent/connectors/rest.py`
- Test: `tests/test_connectors_rest.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_connectors_rest.py`:

```python
import pytest
import httpx
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_connectors_rest.py::test_get_status_returns_mcp_schedules_kv tests/test_connectors_rest.py::test_get_info_returns_profile_content tests/test_connectors_rest.py::test_get_info_unknown_name_returns_404 tests/test_connectors_rest.py::test_get_info_no_profile_path_returns_404 -v
```

Expected: routing 404 or `TypeError` — the routes don't exist yet.

- [ ] **Step 3: Update RESTConnector**

Replace the entire contents of `agent/connectors/rest.py` with:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent.connectors import Connector, InboundEvent, Message, OnMessage, OutboundMessage

if TYPE_CHECKING:
    from agent.store import Store
    from agent.mcp import MCPClient

_SENSITIVE_KV_PREFIXES = ("captured_secret:", "pending_secret_key")

_PROFILE_FILES = {
    "personality": "PERSONALITY.md",
    "protocols": "PROTOCOLS.md",
    "user": "USER.md",
    "checkin": "CHECKIN.md",
}


class RESTConnector(Connector):
    def __init__(
        self,
        port: int = 8080,
        push_channel: tuple[str, str] | None = None,
        store: "Store | None" = None,
        mcp: "MCPClient | None" = None,
        profile_path: Path | None = None,
    ) -> None:
        self._port = port
        self._push_channel = push_channel
        self._store = store
        self._mcp = mcp
        self._profile_path = profile_path
        self._on_message: OnMessage | None = None
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._server: Any = None
        self.app = Starlette(routes=[
            Route("/chat", self._handle_chat, methods=["POST"]),
            Route("/event", self._handle_event, methods=["POST"]),
            Route("/api/status", self._handle_status, methods=["GET"]),
            Route("/api/info/{name}", self._handle_info, methods=["GET"]),
        ])

    async def start(self, on_message: OnMessage) -> None:
        self._on_message = on_message
        import uvicorn
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        await self._server.serve()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

    async def send(self, to: str, message: OutboundMessage) -> None:
        future = self._pending.pop(to, None)
        if future is not None and not future.done():
            future.set_result(message.text)

    async def send_typing(self, to: str) -> None:
        pass

    async def _handle_chat(self, request: Request) -> JSONResponse:
        data = await request.json()
        channel = str(uuid4())
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending[channel] = future

        msg = Message(text=data["message"], sender=channel, sender_name="api")
        event = InboundEvent(channel=channel, message=msg, connector_name="rest")

        if self._on_message is not None:
            await self._on_message(event)

        try:
            reply = await asyncio.wait_for(asyncio.shield(future), timeout=120.0)
        except (asyncio.TimeoutError, TimeoutError):
            self._pending.pop(channel, None)
            return JSONResponse({"error": "timeout"}, status_code=504)
        except asyncio.CancelledError:
            self._pending.pop(channel, None)
            return JSONResponse({"error": "cancelled"}, status_code=503)
        finally:
            self._pending.pop(channel, None)

        return JSONResponse({"reply": reply})

    async def _handle_event(self, request: Request) -> JSONResponse:
        """Fire-and-forget inbound event (e.g. from Home Assistant automations).
        Routes the reply to the configured push_channel (typically Telegram)."""
        if self._on_message is None or self._push_channel is None:
            return JSONResponse({"status": "ignored"})
        data = await request.json()
        text = data.get("message") or data.get("text", "")
        if not text:
            return JSONResponse({"error": "missing message"}, status_code=400)
        connector_name, channel = self._push_channel
        sender = data.get("sender", "homeassistant")
        msg = Message(text=text, sender=sender, sender_name=sender)
        event = InboundEvent(channel=channel, message=msg, connector_name=connector_name)
        asyncio.create_task(self._on_message(event))
        return JSONResponse({"status": "ok"})

    async def _handle_status(self, request: Request) -> JSONResponse:
        schedules: list[dict] = []
        kv: dict[str, str] = {}
        mcp: dict[str, bool] = {}

        if self._store is not None:
            raw_schedules = await self._store.list_schedules()
            schedules = [
                {"name": s.name, "cron": s.cron, "fire_at": s.fire_at}
                for s in raw_schedules
            ]
            raw_kv = await self._store.kv_list()
            kv = {
                k: v for k, v in raw_kv
                if not any(k.startswith(p) or k == p for p in _SENSITIVE_KV_PREFIXES)
            }

        if self._mcp is not None:
            mcp = self._mcp.server_status()

        return JSONResponse({"mcp": mcp, "schedules": schedules, "kv": kv})

    async def _handle_info(self, request: Request) -> JSONResponse:
        name = request.path_params["name"]
        if name not in _PROFILE_FILES or self._profile_path is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        path = self._profile_path / _PROFILE_FILES[name]
        if not path.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"content": path.read_text()})
```

- [ ] **Step 4: Run all REST connector tests**

```
uv run pytest tests/test_connectors_rest.py -v
```

Expected: all PASS (including pre-existing tests)

- [ ] **Step 5: Commit**

```bash
git add agent/connectors/rest.py tests/test_connectors_rest.py
git commit -m "feat: add /api/status and /api/info endpoints to RESTConnector"
```

---

## Task 4: Wire agent changes in main.py

**Files:**
- Modify: `agent/main.py`

- [ ] **Step 1: Update RESTConnector construction in main.py**

Find this block in `agent/main.py` (around line 183):

```python
        if "rest" in args.connectors:
            push_channel: tuple[str, str] | None = None
            if settings.telegram is not None and settings.telegram.allowed_chat_ids:
                push_channel = ("telegram", str(settings.telegram.allowed_chat_ids[0]))
            connectors["rest"] = RESTConnector(push_channel=push_channel)
```

Replace with:

```python
        if "rest" in args.connectors:
            push_channel: tuple[str, str] | None = None
            if settings.telegram is not None and settings.telegram.allowed_chat_ids:
                push_channel = ("telegram", str(settings.telegram.allowed_chat_ids[0]))
            connectors["rest"] = RESTConnector(
                push_channel=push_channel,
                store=store,
                mcp=mcp,
                profile_path=settings.profile_path,
            )
```

- [ ] **Step 2: Run the full test suite**

```
uv run pytest tests/ --ignore=tests/test_live_agent.py -v
```

Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add agent/main.py
git commit -m "feat: pass store/mcp/profile_path to RESTConnector"
```

---

## Task 5: Scaffold the web app

**Files:**
- Create: `web/requirements.txt`
- Create: `web/Dockerfile`
- Create: `web/docker-compose.yml`
- Create: `web/tests/__init__.py`

- [ ] **Step 1: Create `web/requirements.txt`**

```
starlette>=0.46
uvicorn>=0.34
httpx>=0.28
respx>=0.21
pytest>=8
pytest-asyncio>=0.24
anyio[trio]>=4
```

- [ ] **Step 2: Create `web/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt
COPY . .
ENV HOST=0.0.0.0
ENV PORT=3000
ENV AGENT_URL=http://localhost:8080
CMD ["python", "app.py"]
```

- [ ] **Step 3: Create `web/docker-compose.yml`**

```yaml
services:
  web:
    build: .
    ports:
      - "3000:3000"
    environment:
      AGENT_URL: http://host.docker.internal:8080
      HOST: 0.0.0.0
      PORT: 3000
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Note: `extra_hosts` makes `host.docker.internal` resolve on Linux. On macOS Docker Desktop it resolves automatically without this entry.

- [ ] **Step 4: Create `web/tests/__init__.py`** (empty file)

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "chore: scaffold web app directory"
```

---

## Task 6: Create `web/app.py`

**Files:**
- Create: `web/app.py`
- Create: `web/pages/index.html` (placeholder)
- Create: `web/pages/info.html` (placeholder)
- Create: `web/static/.gitkeep`
- Create: `web/tests/test_app.py`

- [ ] **Step 1: Write failing tests**

Create `web/tests/test_app.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import respx

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app  # noqa: E402


@respx.mock
def test_proxy_chat_forwards_and_returns_reply():
    respx.post("http://localhost:8080/chat").mock(
        return_value=httpx.Response(200, json={"reply": "pong"})
    )
    with httpx.Client(app=app, base_url="http://test") as c:
        r = c.post("/proxy/chat", json={"message": "ping"})
    assert r.status_code == 200
    assert r.json() == {"reply": "pong"}


@respx.mock
def test_proxy_status_forwards():
    respx.get("http://localhost:8080/api/status").mock(
        return_value=httpx.Response(200, json={"mcp": {}, "schedules": [], "kv": {}})
    )
    with httpx.Client(app=app, base_url="http://test") as c:
        r = c.get("/proxy/api/status")
    assert r.status_code == 200
    assert "mcp" in r.json()


@respx.mock
def test_proxy_info_forwards():
    respx.get("http://localhost:8080/api/info/user").mock(
        return_value=httpx.Response(200, json={"content": "# User\nCharlie."})
    )
    with httpx.Client(app=app, base_url="http://test") as c:
        r = c.get("/proxy/api/info/user")
    assert r.status_code == 200
    assert r.json()["content"] == "# User\nCharlie."


def test_index_serves_html():
    with httpx.Client(app=app, base_url="http://test") as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_info_page_serves_html():
    with httpx.Client(app=app, base_url="http://test") as c:
        r = c.get("/info/personality")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
```

- [ ] **Step 2: Run tests to verify they fail**

First install deps: `cd web && pip install -r requirements.txt`

```
cd web && python -m pytest tests/test_app.py -v
```

Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Create placeholder page files**

`web/pages/index.html`:
```html
<!DOCTYPE html><html><body>chat</body></html>
```

`web/pages/info.html`:
```html
<!DOCTYPE html><html><body>info</body></html>
```

Create `web/static/.gitkeep` (empty).

- [ ] **Step 4: Create `web/app.py`**

```python
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8080")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "3000"))

_HERE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: Starlette):
    async with httpx.AsyncClient(base_url=AGENT_URL, timeout=130.0) as client:
        app.state.client = client
        yield


async def index(request: Request) -> FileResponse:
    return FileResponse(_HERE / "pages" / "index.html")


async def info_page(request: Request) -> FileResponse:
    return FileResponse(_HERE / "pages" / "info.html")


async def proxy_chat(request: Request) -> Response:
    body = await request.body()
    r = await request.app.state.client.post(
        "/chat", content=body, headers={"content-type": "application/json"}
    )
    return JSONResponse(r.json(), status_code=r.status_code)


async def proxy_status(request: Request) -> Response:
    r = await request.app.state.client.get("/api/status")
    return JSONResponse(r.json(), status_code=r.status_code)


async def proxy_info(request: Request) -> Response:
    name = request.path_params["name"]
    r = await request.app.state.client.get(f"/api/info/{name}")
    return JSONResponse(r.json(), status_code=r.status_code)


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/", index),
        Route("/info/{name}", info_page),
        Route("/proxy/chat", proxy_chat, methods=["POST"]),
        Route("/proxy/api/status", proxy_status),
        Route("/proxy/api/info/{name}", proxy_info),
        Mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static"),
    ],
)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd web && python -m pytest tests/test_app.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add web/app.py web/pages/ web/static/ web/tests/
git commit -m "feat: add web app proxy routes"
```

---

## Task 7: Create pages and CSS

**Files:**
- Modify: `web/pages/index.html`
- Modify: `web/pages/info.html`
- Create: `web/static/style.css`

- [ ] **Step 1: Write `web/static/style.css`**

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body { height: 100%; background: #0d0d1a; color: #ccc; font-family: system-ui, sans-serif; font-size: 15px; }

.layout {
  display: flex;
  height: 100vh;
}

.chat-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #1e1e2e;
}

.sidebar-col {
  width: 220px;
  flex-shrink: 0;
}

agent-chat {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 32px;
}

nav { margin-bottom: 24px; }
nav a { color: #6688bb; text-decoration: none; font-size: 14px; }
nav a:hover { color: #88aadd; }
```

- [ ] **Step 2: Write `web/pages/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>awfulclaw</title>
  <link rel="stylesheet" href="/static/style.css">
  <script type="module" src="/static/components/agent-chat.js"></script>
  <script type="module" src="/static/components/agent-sidebar.js"></script>
</head>
<body>
  <div class="layout">
    <main class="chat-col">
      <agent-chat></agent-chat>
    </main>
    <aside class="sidebar-col">
      <agent-sidebar></agent-sidebar>
    </aside>
  </div>
</body>
</html>
```

- [ ] **Step 3: Write `web/pages/info.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>awfulclaw — info</title>
  <link rel="stylesheet" href="/static/style.css">
  <script type="module" src="/static/components/profile-viewer.js"></script>
</head>
<body>
  <div class="page">
    <nav><a href="/">&#8592; back</a></nav>
    <profile-viewer></profile-viewer>
  </div>
</body>
</html>
```

- [ ] **Step 4: Verify tests still pass**

```
cd web && python -m pytest tests/test_app.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add web/pages/ web/static/style.css
git commit -m "feat: add index and info pages with layout CSS"
```

---

## Task 8: Create `<agent-chat>` web component

**Files:**
- Create: `web/static/components/agent-chat.js`

No automated tests — verify by running the app and chatting in the browser.

- [ ] **Step 1: Create `web/static/components/agent-chat.js`**

All dynamic content uses `textContent` or `createElement` — never `innerHTML` with variable data.

```javascript
class AgentChat extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._messages = [];
    this._busy = false;
  }

  connectedCallback() {
    const style = document.createElement('style');
    style.textContent = `
      :host { display: flex; flex-direction: column; height: 100%; }
      .messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
      .message { max-width: 70%; padding: 8px 12px; border-radius: 12px; line-height: 1.5; word-break: break-word; white-space: pre-wrap; }
      .message.user { align-self: flex-end; background: #1a3a5c; border-radius: 12px 12px 2px 12px; color: #aac; }
      .message.agent { align-self: flex-start; background: #1e1e2e; border-radius: 12px 12px 12px 2px; color: #ccc; }
      .message.error { align-self: flex-start; background: #3c1515; color: #e88; }
      .typing { align-self: flex-start; color: #555; font-size: 13px; padding: 8px 12px; }
      .input-row { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #1e1e2e; }
      textarea { flex: 1; background: #1e1e2e; border: 1px solid #333; border-radius: 8px; padding: 8px 12px; color: #ccc; font-family: inherit; font-size: 14px; resize: none; height: 42px; }
      textarea:focus { outline: none; border-color: #446; }
      button { background: #2a4a7c; border: none; border-radius: 8px; padding: 8px 16px; color: #88aacc; cursor: pointer; font-size: 14px; }
      button:disabled { opacity: 0.4; cursor: default; }
    `;

    this._messagesEl = document.createElement('div');
    this._messagesEl.className = 'messages';

    const inputRow = document.createElement('div');
    inputRow.className = 'input-row';

    this._input = document.createElement('textarea');
    this._input.placeholder = 'Type a message\u2026';
    this._input.rows = 1;

    this._button = document.createElement('button');
    this._button.textContent = 'Send';

    inputRow.appendChild(this._input);
    inputRow.appendChild(this._button);

    this.shadowRoot.appendChild(style);
    this.shadowRoot.appendChild(this._messagesEl);
    this.shadowRoot.appendChild(inputRow);

    this._button.addEventListener('click', () => this._send());
    this._input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._send(); }
    });
  }

  _redraw() {
    this._messagesEl.replaceChildren();
    for (const msg of this._messages) {
      const el = document.createElement('div');
      el.className = 'message ' + msg.role + (msg.error ? ' error' : '');
      el.textContent = msg.text;
      this._messagesEl.appendChild(el);
    }
    if (this._busy) {
      const el = document.createElement('div');
      el.className = 'typing';
      el.textContent = 'thinking\u2026';
      this._messagesEl.appendChild(el);
    }
    this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
  }

  async _send() {
    const text = this._input.value.trim();
    if (!text || this._busy) return;
    this._input.value = '';
    this._messages.push({ role: 'user', text });
    this._busy = true;
    this._button.disabled = true;
    this._redraw();

    try {
      const r = await fetch('/proxy/chat', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await r.json();
      if (data.error) {
        this._messages.push({ role: 'agent', error: true, text: 'Error: ' + data.error });
      } else {
        this._messages.push({ role: 'agent', text: data.reply });
      }
    } catch {
      this._messages.push({ role: 'agent', error: true, text: 'Failed to reach agent.' });
    } finally {
      this._busy = false;
      this._button.disabled = false;
      this._redraw();
    }
  }
}

customElements.define('agent-chat', AgentChat);
```

- [ ] **Step 2: Smoke-test manually**

Start the agent with the REST connector, then start the web app:

```bash
# In awfulclaw root:
uv run python -m agent.main --connector rest

# In web/:
python app.py
```

Open http://localhost:3000, send a message, verify a reply appears.

- [ ] **Step 3: Commit**

```bash
git add web/static/components/agent-chat.js
git commit -m "feat: add <agent-chat> web component"
```

---

## Task 9: Create `<agent-sidebar>` web component

**Files:**
- Create: `web/static/components/agent-sidebar.js`

All dynamic content (server names, schedule names, KV values) is set via `textContent` — no `innerHTML` with variable data.

- [ ] **Step 1: Create `web/static/components/agent-sidebar.js`**

```javascript
function _el(tag, opts = {}) {
  const el = document.createElement(tag);
  if (opts.cls) el.className = opts.cls;
  if (opts.text) el.textContent = opts.text;
  if (opts.href) { el.href = opts.href; }
  return el;
}

class AgentSidebar extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = `
      :host { display: block; height: 100%; overflow-y: auto; padding: 16px; background: #10101e; box-sizing: border-box; }
      h3 { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #444; margin: 0 0 8px; }
      .section { margin-bottom: 16px; }
      hr { border: none; border-top: 1px solid #1e1e2e; margin: 12px 0; }
      a { color: #6688bb; text-decoration: none; font-size: 13px; display: block; margin-bottom: 4px; }
      a:hover { color: #88aadd; }
      .server { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
      .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: #6b3030; }
      .dot.on { background: #2d6a4f; }
      .sname { font-size: 12px; color: #aaa; }
      .kv-row { font-size: 12px; margin-bottom: 4px; display: flex; gap: 6px; }
      .kv-key { color: #555; }
      .kv-val { color: #888; }
      .sched { font-size: 12px; color: #aaa; margin-bottom: 4px; display: flex; gap: 6px; flex-wrap: wrap; }
      .expr { color: #555; font-size: 11px; }
      .empty { font-size: 12px; color: #333; }
    `;
    this.shadowRoot.appendChild(style);

    // Profile links (static — no dynamic content)
    const profileSection = this._section('Profile');
    for (const [label, path] of [
      ['Personality', '/info/personality'],
      ['Protocols', '/info/protocols'],
      ['User', '/info/user'],
      ['Check-in', '/info/checkin'],
    ]) {
      const a = _el('a', { text: label + ' \u2192', href: path });
      profileSection.appendChild(a);
    }
    this.shadowRoot.appendChild(profileSection);
    this.shadowRoot.appendChild(document.createElement('hr'));

    this._mcpSection = this._section('MCP Servers');
    this._mcpList = _el('div');
    this._mcpList.appendChild(_el('span', { cls: 'empty', text: 'loading\u2026' }));
    this._mcpSection.appendChild(this._mcpList);
    this.shadowRoot.appendChild(this._mcpSection);
    this.shadowRoot.appendChild(document.createElement('hr'));

    this._schedSection = this._section('Schedules');
    this._schedList = _el('div');
    this._schedList.appendChild(_el('span', { cls: 'empty', text: 'loading\u2026' }));
    this._schedSection.appendChild(this._schedList);
    this.shadowRoot.appendChild(this._schedSection);
    this.shadowRoot.appendChild(document.createElement('hr'));

    this._kvSection = this._section('Config');
    this._kvList = _el('div');
    this._kvList.appendChild(_el('span', { cls: 'empty', text: 'loading\u2026' }));
    this._kvSection.appendChild(this._kvList);
    this.shadowRoot.appendChild(this._kvSection);

    this._load();
    this._interval = setInterval(() => this._load(), 60000);
  }

  disconnectedCallback() {
    clearInterval(this._interval);
  }

  _section(title) {
    const div = _el('div', { cls: 'section' });
    const h3 = _el('h3', { text: title });
    div.appendChild(h3);
    return div;
  }

  async _load() {
    try {
      const r = await fetch('/proxy/api/status');
      if (!r.ok) return;
      const data = await r.json();
      this._renderMcp(data.mcp || {});
      this._renderSchedules(data.schedules || []);
      this._renderKv(data.kv || {});
    } catch { /* silently ignore — stale UI is acceptable */ }
  }

  _renderMcp(mcp) {
    this._mcpList.replaceChildren();
    const entries = Object.entries(mcp);
    if (!entries.length) {
      this._mcpList.appendChild(_el('span', { cls: 'empty', text: 'none' }));
      return;
    }
    for (const [name, connected] of entries) {
      const row = _el('div', { cls: 'server' });
      const dot = _el('div', { cls: 'dot' + (connected ? ' on' : '') });
      const label = _el('span', { cls: 'sname', text: name });
      row.appendChild(dot);
      row.appendChild(label);
      this._mcpList.appendChild(row);
    }
  }

  _renderSchedules(schedules) {
    this._schedList.replaceChildren();
    if (!schedules.length) {
      this._schedList.appendChild(_el('span', { cls: 'empty', text: 'none' }));
      return;
    }
    for (const s of schedules) {
      const row = _el('div', { cls: 'sched' });
      row.appendChild(_el('span', { text: s.name }));
      if (s.cron || s.fire_at) {
        row.appendChild(_el('span', { cls: 'expr', text: s.cron || s.fire_at }));
      }
      this._schedList.appendChild(row);
    }
  }

  _renderKv(kv) {
    this._kvList.replaceChildren();
    const entries = Object.entries(kv);
    if (!entries.length) {
      this._kvList.appendChild(_el('span', { cls: 'empty', text: 'empty' }));
      return;
    }
    for (const [k, v] of entries) {
      const row = _el('div', { cls: 'kv-row' });
      row.appendChild(_el('span', { cls: 'kv-key', text: k }));
      row.appendChild(_el('span', { cls: 'kv-val', text: v }));
      this._kvList.appendChild(row);
    }
  }
}

customElements.define('agent-sidebar', AgentSidebar);
```

- [ ] **Step 2: Smoke-test manually**

Open http://localhost:3000, verify the sidebar loads with MCP status, schedules, and KV config. Click a profile link.

- [ ] **Step 3: Commit**

```bash
git add web/static/components/agent-sidebar.js
git commit -m "feat: add <agent-sidebar> web component"
```

---

## Task 10: Create `<profile-viewer>` web component

**Files:**
- Create: `web/static/components/profile-viewer.js`

The markdown renderer HTML-escapes all source text before substituting any tags, so no user-controlled content reaches the DOM unescaped.

- [ ] **Step 1: Create `web/static/components/profile-viewer.js`**

```javascript
/**
 * Minimal markdown renderer for profile files.
 * All source text is HTML-escaped before any tag substitution.
 * Supports: h1-h3, bold, italic, inline code, unordered lists, paragraphs.
 */
function _escape(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _inline(text) {
  // text is already HTML-escaped — only add safe tags
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>');
}

function _md(raw) {
  const lines = raw.split('\n');
  const parts = [];
  let inList = false;

  for (const line of lines) {
    const escaped = _escape(line);
    const h3 = escaped.match(/^### (.+)/);
    const h2 = escaped.match(/^## (.+)/);
    const h1 = escaped.match(/^# (.+)/);
    const li = escaped.match(/^[-*] (.+)/);

    if ((h1 || h2 || h3 || escaped.trim() === '') && inList) {
      parts.push('</ul>');
      inList = false;
    }

    if (h3)            parts.push('<h3>' + _inline(h3[1]) + '</h3>');
    else if (h2)       parts.push('<h2>' + _inline(h2[1]) + '</h2>');
    else if (h1)       parts.push('<h1>' + _inline(h1[1]) + '</h1>');
    else if (li)       {
      if (!inList) { parts.push('<ul>'); inList = true; }
      parts.push('<li>' + _inline(li[1]) + '</li>');
    }
    else if (escaped.trim() === '') parts.push('');
    else               parts.push('<p>' + _inline(escaped) + '</p>');
  }

  if (inList) parts.push('</ul>');
  return parts.join('\n');
}

class ProfileViewer extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = `
      :host { display: block; }
      h1 { font-size: 1.6em; color: #aac; margin-bottom: 16px; }
      h2 { font-size: 1.2em; color: #99b; margin: 20px 0 8px; }
      h3 { font-size: 1em; color: #889; margin: 16px 0 6px; }
      p, li { color: #ccc; line-height: 1.6; margin-bottom: 8px; }
      ul { padding-left: 20px; margin-bottom: 8px; }
      code { background: #1e1e2e; padding: 2px 6px; border-radius: 4px; font-family: monospace; color: #88aacc; font-size: 0.9em; }
      strong { color: #ddd; }
    `;

    this._content = document.createElement('div');

    const loading = document.createElement('p');
    loading.style.color = '#555';
    loading.style.fontStyle = 'italic';
    loading.textContent = 'Loading\u2026';
    this._content.appendChild(loading);

    this.shadowRoot.appendChild(style);
    this.shadowRoot.appendChild(this._content);

    const name = window.location.pathname.split('/').filter(Boolean).pop() || '';
    this._load(name);
  }

  async _load(name) {
    try {
      const r = await fetch('/proxy/api/info/' + encodeURIComponent(name));
      if (!r.ok) {
        this._content.replaceChildren();
        const err = document.createElement('p');
        err.style.color = '#e88';
        err.textContent = 'Not found.';
        this._content.appendChild(err);
        return;
      }
      const { content } = await r.json();
      // _md() HTML-escapes all source text before generating tags
      this._content.innerHTML = _md(content);
    } catch {
      this._content.replaceChildren();
      const err = document.createElement('p');
      err.style.color = '#e88';
      err.textContent = 'Failed to load.';
      this._content.appendChild(err);
    }
  }
}

customElements.define('profile-viewer', ProfileViewer);
```

- [ ] **Step 2: Smoke-test manually**

Open http://localhost:3000, click "User →" in the sidebar, verify the profile renders with heading and paragraph formatting.

- [ ] **Step 3: Run the full web test suite**

```
cd web && python -m pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 4: Run the full agent test suite**

```
cd .. && uv run pytest tests/ --ignore=tests/test_live_agent.py -v
```

Expected: all PASS

- [ ] **Step 5: Final commit**

```bash
git add web/static/components/profile-viewer.js
git commit -m "feat: add <profile-viewer> web component"
```
