"""Telegram connector — read and send messages via the Bot API."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

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


_OFFSET_PATH = Path("memory/.telegram_offset")

# Rate limiting: max messages per window
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 10  # max messages per window
_MAX_MESSAGE_LENGTH = 4000  # characters


class TelegramConnector(Connector):
    def __init__(self) -> None:
        self._token = _get_token()
        self._chat_id = _get_chat_id()
        self._offset: int = self._load_offset()
        self._base = f"https://api.telegram.org/bot{self._token}"
        self._msg_timestamps: list[float] = []

    def _load_offset(self) -> int:
        try:
            if _OFFSET_PATH.exists():
                return int(_OFFSET_PATH.read_text().strip())
        except Exception:
            pass
        return 0

    def _save_offset(self) -> None:
        try:
            _OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
            _OFFSET_PATH.write_text(str(self._offset))
        except Exception:
            pass

    @property
    def primary_recipient(self) -> str:
        return self._chat_id

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
            sender_id = str(msg.get("from", {}).get("id", ""))
            if chat_id != self._chat_id or sender_id != self._chat_id:
                continue

            # Rate limiting
            now = time.monotonic()
            self._msg_timestamps = [
                t for t in self._msg_timestamps if now - t < _RATE_LIMIT_WINDOW
            ]
            if len(self._msg_timestamps) >= _RATE_LIMIT_MAX:
                logger.warning("Rate limit exceeded, dropping message")
                continue
            self._msg_timestamps.append(now)

            text: str = msg.get("text") or ""
            location = msg.get("location")
            photo = msg.get("photo")
            if not text and not location and not photo:
                continue

            # Truncate oversized messages
            if len(text) > _MAX_MESSAGE_LENGTH:
                text = text[:_MAX_MESSAGE_LENGTH] + "\n[truncated]"

            ts = datetime.fromtimestamp(msg["date"], tz=timezone.utc)
            sender = str(msg.get("from", {}).get("id", ""))

            if location:
                body = f"[Location: {location['latitude']}, {location['longitude']}]"
                messages.append(Message(sender=sender, body=body, timestamp=ts, is_from_me=False))
            elif photo:
                caption: str = msg.get("caption") or "[image]"
                image_data, image_mime = self._download_photo(photo)
                messages.append(
                    Message(
                        sender=sender,
                        body=caption,
                        timestamp=ts,
                        is_from_me=False,
                        image_data=image_data,
                        image_mime=image_mime,
                    )
                )
            else:
                messages.append(
                    Message(sender=sender, body=text, timestamp=ts, is_from_me=False)
                )

        if updates:
            self._save_offset()
        return messages

    def _download_photo(self, photo: list[dict[str, object]]) -> tuple[bytes, str]:
        """Download the largest photo variant and return (bytes, mime_type)."""
        def _file_size(p: dict[str, object]) -> int:
            v = p.get("file_size")
            return int(str(v)) if v is not None else 0

        largest = max(photo, key=_file_size)
        file_id = str(largest["file_id"])
        try:
            file_resp = httpx.get(
                f"{self._base}/getFile", params={"file_id": file_id}, timeout=10
            )
            file_resp.raise_for_status()
            file_path = file_resp.json()["result"]["file_path"]
            dl_url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
            img_resp = httpx.get(dl_url, timeout=30)
            img_resp.raise_for_status()
            return img_resp.content, "image/jpeg"
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to download Telegram photo: {exc}") from exc

    def send_message(self, to: str, body: str) -> None:
        payload = {"chat_id": self._chat_id, "text": body}
        try:
            resp = httpx.post(f"{self._base}/sendMessage", json=payload, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Telegram sendMessage failed: {exc}") from exc
