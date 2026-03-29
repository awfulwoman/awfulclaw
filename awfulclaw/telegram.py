"""Telegram connector — read and send messages via the Bot API."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

from awfulclaw.connector import Connector, Message

logger = logging.getLogger(__name__)


def _get_token() -> str:
    value = os.getenv("TELEGRAM_BOT_TOKEN")
    if not value:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot via @BotFather on Telegram "
            "and set the token in your .env file:\n\n"
            "  TELEGRAM_BOT_TOKEN=123456:ABC-DEF...\n"
        )
    return value


def _get_chat_id() -> str:
    value = os.getenv("TELEGRAM_CHAT_ID")
    if not value:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is not set. To find your chat ID, send a message to your "
            "bot and call https://api.telegram.org/bot<TOKEN>/getUpdates — the chat id "
            "appears in the response. Then add it to your .env file:\n\n"
            "  TELEGRAM_CHAT_ID=123456789\n"
        )
    return value


class TelegramConnector(Connector):
    def __init__(self) -> None:
        self._token = _get_token()
        self._chat_id = _get_chat_id()
        self._offset: int = 0
        self._base = f"https://api.telegram.org/bot{self._token}"

    def poll_new_messages(self, since: datetime) -> list[Message]:
        params: dict[str, int | str] = {"timeout": 30, "offset": self._offset}
        try:
            resp = httpx.get(f"{self._base}/getUpdates", params=params, timeout=35)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Telegram getUpdates failed: %s", exc)
            return []

        data = resp.json()
        updates = data.get("result", [])
        messages: list[Message] = []
        for update in updates:
            update_id: int = update["update_id"]
            self._offset = max(self._offset, update_id + 1)

            msg = update.get("message")
            if not msg:
                continue  # ignore edits, joins, etc.

            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != self._chat_id:
                continue

            text: str = msg.get("text") or ""
            if not text:
                continue

            ts = datetime.fromtimestamp(msg["date"], tz=timezone.utc)
            sender = str(msg.get("from", {}).get("id", ""))

            messages.append(Message(sender=sender, body=text, timestamp=ts, is_from_me=False))

        return messages

    def send_message(self, to: str, body: str) -> None:
        payload = {"chat_id": self._chat_id, "text": body}
        try:
            resp = httpx.post(f"{self._base}/sendMessage", json=payload, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Telegram sendMessage failed: {exc}") from exc
