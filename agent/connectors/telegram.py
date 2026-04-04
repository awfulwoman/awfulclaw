from __future__ import annotations

import asyncio
from typing import Any

import httpx

from agent.connectors import Connector, InboundEvent, Message, OnMessage, OutboundMessage
from agent.transcriber import Transcriber


_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramConnector(Connector):
    def __init__(self, token: str, allowed_chat_ids: list[int], store: Any, owner_id: int | None = None, transcriber: "Transcriber | None" = None) -> None:
        self._token = token
        self._allowed_chat_ids = set(allowed_chat_ids)
        self._store = store
        self._owner_id = owner_id
        self._transcriber = transcriber
        self._running = False
        self._client: httpx.AsyncClient | None = None

    def _url(self, method: str) -> str:
        return _BASE.format(token=self._token, method=method)

    async def start(self, on_message: OnMessage) -> None:
        self._running = True
        async with httpx.AsyncClient(timeout=35.0) as client:
            self._client = client
            while self._running:
                try:
                    await self._poll(client, on_message)
                except Exception:
                    await asyncio.sleep(1.0)
        self._client = None

    async def stop(self) -> None:
        self._running = False

    async def send(self, to: str, message: OutboundMessage) -> None:
        if self._client is None:
            async with httpx.AsyncClient() as client:
                await client.post(self._url("sendMessage"), json={"chat_id": int(to), "text": message.text})
        else:
            await self._client.post(self._url("sendMessage"), json={"chat_id": int(to), "text": message.text})

    async def send_typing(self, to: str) -> None:
        if self._client is None:
            async with httpx.AsyncClient() as client:
                await client.post(self._url("sendChatAction"), json={"chat_id": int(to), "action": "typing"})
        else:
            await self._client.post(self._url("sendChatAction"), json={"chat_id": int(to), "action": "typing"})

    async def _poll(self, client: httpx.AsyncClient, on_message: OnMessage) -> None:
        offset_str = await self._store.kv_get("telegram_offset")
        offset = int(offset_str) if offset_str is not None else 0

        resp = await client.get(
            self._url("getUpdates"),
            params={"offset": offset, "timeout": 30, "limit": 100},
        )
        data = resp.json()
        updates: list[dict[str, Any]] = data.get("result", [])

        if not updates:
            return

        # Group messages by chat_id
        batches: dict[int, list[dict[str, Any]]] = {}
        new_offset = offset
        for update in updates:
            new_offset = max(new_offset, update["update_id"] + 1)
            msg = update.get("message")
            if msg is None:
                continue
            chat_id: int = msg["chat"]["id"]
            if chat_id not in self._allowed_chat_ids:
                continue
            batches.setdefault(chat_id, []).append(msg)

        await self._store.kv_set("telegram_offset", str(new_offset))

        for chat_id, msgs in batches.items():
            parts: list[str] = []
            for m in msgs:
                text = await self._resolve_text(m, chat_id)
                if text:
                    parts.append(text)
            combined = "\n".join(parts)
            if not combined:
                continue

            first = msgs[0]
            from_user = first.get("from", {})
            sender_id = str(from_user.get("id", chat_id))
            sender_name = from_user.get("first_name", sender_id)

            message = Message(text=combined, sender=sender_id, sender_name=sender_name)
            event = InboundEvent(channel=str(chat_id), message=message, connector_name="telegram")
            await on_message(event)

    async def _resolve_text(self, msg: dict[str, Any], chat_id: int) -> str:
        if "text" in msg:
            return self._frame(msg)
        if "voice" in msg and self._transcriber is not None:
            try:
                audio = await self._download_voice(msg["voice"]["file_id"])
                transcript = await self._transcriber.transcribe(audio, "audio/ogg")
                framed = dict(msg)
                framed["text"] = f"[Voice]: {transcript}"
                return self._frame(framed)
            except Exception:
                await self.send(str(chat_id), OutboundMessage(text="Sorry, I couldn't transcribe that voice note."))
                return ""
        return self._frame(msg)

    async def _download_voice(self, file_id: str) -> bytes:
        assert self._client is not None  # always set when called from _poll
        resp = await self._client.get(self._url("getFile"), params={"file_id": file_id})
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        resp = await self._client.get(file_url)
        resp.raise_for_status()
        return resp.content

    def _frame(self, msg: dict[str, Any]) -> str:
        text = msg.get("text", "")
        from_user = msg.get("from", {})
        sender_id = from_user.get("id")
        is_owner = self._owner_id is not None and sender_id == self._owner_id
        username = from_user.get("username") or from_user.get("first_name", str(sender_id))
        chat_type = msg.get("chat", {}).get("type", "private")
        is_group = chat_type in ("group", "supergroup")

        if is_group and not is_owner:
            return f'<untrusted-content source="chat-user" from="{username}">{text}</untrusted-content>'
        return text

    @classmethod
    async def verify_token(cls, token: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(_BASE.format(token=token, method="getMe"))
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
