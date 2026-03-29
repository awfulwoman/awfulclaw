"""iMessage connector — read and send messages via osascript (macOS only)."""

from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from awfulclaw.connector import Connector, Message

# macOS stores iMessage timestamps as seconds since 2001-01-01 (Cocoa epoch)
_COCOA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
_CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


def poll_new_messages(since: datetime) -> list[Message]:
    """Return incoming messages (is_from_me=False) with timestamp > since."""
    if not _CHAT_DB.exists():
        return []
    try:
        return _query_chat_db(since)
    except Exception:
        return []


def _query_chat_db(since: datetime) -> list[Message]:
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    since_cocoa = (since - _COCOA_EPOCH).total_seconds() * 1_000_000_000  # nanoseconds

    con = sqlite3.connect(f"file:{_CHAT_DB}?mode=ro", uri=True)
    try:
        cur = con.execute(
            """
            SELECT
                COALESCE(h.id, ''),
                m.text,
                m.date,
                m.is_from_me
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.date > ?
              AND m.is_from_me = 0
              AND m.text IS NOT NULL
            ORDER BY m.date ASC
            """,
            (since_cocoa,),
        )
        rows = cur.fetchall()
    finally:
        con.close()

    messages: list[Message] = []
    for sender, body, date_ns, is_from_me in rows:
        ts = _COCOA_EPOCH + timedelta(microseconds=int(date_ns) // 1000)
        messages.append(
            Message(
                sender=sender,
                body=body,
                timestamp=ts,
                is_from_me=bool(is_from_me),
            )
        )
    return messages


def send_message(to: str, body: str) -> None:
    """Send an iMessage to a phone number or Apple ID via osascript."""
    # Escape backslashes first, then quotes, to avoid breaking the AppleScript string literal.
    safe_body = body.replace("\\", "\\\\").replace('"', '\\"')
    script = f"""
tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy "{to}" of targetService
    send "{safe_body}" to targetBuddy
end tell
"""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"osascript failed (exit {result.returncode}): {result.stderr.strip()}"
        )


class IMessageConnector(Connector):
    def __init__(self) -> None:
        from awfulclaw import config
        self._phone = config.get_phone()

    @property
    def primary_recipient(self) -> str:
        return self._phone

    def poll_new_messages(self, since: datetime) -> list[Message]:
        return poll_new_messages(since)

    def send_message(self, to: str, body: str) -> None:
        send_message(to, body)
