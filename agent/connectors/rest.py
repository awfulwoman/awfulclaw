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
            Route("/api/history", self._handle_history, methods=["GET"]),
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
        reply_id = str(uuid4())
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending[reply_id] = future

        msg = Message(text=data["message"], sender=reply_id, sender_name="api")
        event = InboundEvent(
            channel="primary",
            reply_to=reply_id,
            message=msg,
            connector_name="rest",
        )

        if self._on_message is not None:
            await self._on_message(event)

        try:
            reply = await asyncio.wait_for(asyncio.shield(future), timeout=120.0)
        except (asyncio.TimeoutError, TimeoutError):
            self._pending.pop(reply_id, None)
            return JSONResponse({"error": "timeout"}, status_code=504)
        except asyncio.CancelledError:
            self._pending.pop(reply_id, None)
            return JSONResponse({"error": "cancelled"}, status_code=503)
        finally:
            self._pending.pop(reply_id, None)

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
                if not any(k.startswith(p) for p in _SENSITIVE_KV_PREFIXES)
            }

        if self._mcp is not None:
            mcp = self._mcp.server_status()

        return JSONResponse({"mcp": mcp, "schedules": schedules, "kv": kv})

    async def _handle_history(self, request: Request) -> JSONResponse:
        if self._store is None:
            return JSONResponse({"turns": []})
        limit = min(int(request.query_params.get("limit", "50")), 200)
        turns = await self._store.recent_turns("primary", limit)
        return JSONResponse({
            "turns": [
                {
                    "role": t.role,
                    "content": t.content,
                    "timestamp": t.timestamp,
                    "connector": t.connector,
                }
                for t in turns
            ]
        })

    async def _handle_info(self, request: Request) -> JSONResponse:
        name = request.path_params["name"]
        if name not in _PROFILE_FILES or self._profile_path is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        path = self._profile_path / _PROFILE_FILES[name]
        if not path.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"content": path.read_text()})
