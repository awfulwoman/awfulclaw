from __future__ import annotations

import asyncio
from uuid import uuid4
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent.connectors import Connector, InboundEvent, Message, OnMessage, OutboundMessage


class RESTConnector(Connector):
    def __init__(
        self,
        port: int = 8080,
        push_channel: tuple[str, str] | None = None,
    ) -> None:
        self._port = port
        self._push_channel = push_channel  # (connector_name, channel) for fire-and-forget events
        self._on_message: OnMessage | None = None
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._server: Any = None
        self.app = Starlette(routes=[
            Route("/chat", self._handle_chat, methods=["POST"]),
            Route("/event", self._handle_event, methods=["POST"]),
        ])

    async def start(self, on_message: OnMessage) -> None:
        self._on_message = on_message
        import uvicorn
        config = uvicorn.Config(self.app, host="0.0.0.0", port=self._port, log_level="warning")
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
