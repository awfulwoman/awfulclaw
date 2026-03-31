"""MCP server for reading emails via IMAP."""

from __future__ import annotations

import email
import email.header
import imaplib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("imap_read")


@dataclass
class EmailSummary:
    from_addr: str
    subject: str
    body_preview: str  # first 500 chars of plain-text body
    timestamp: datetime


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, ValueError):
                decoded.append(part.decode("utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded)


def _decode_bytes(payload: bytes, charset: str | None) -> str:
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except (LookupError, ValueError):
        return payload.decode("utf-8", errors="replace")


def _get_plain_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return _decode_bytes(payload, part.get_content_charset())
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            return _decode_bytes(payload, msg.get_content_charset())
    return ""


def _get_env_vars() -> tuple[str, int, str, str]:
    host = os.getenv("IMAP_HOST")
    port = int(os.getenv("IMAP_PORT", "993"))
    user = os.getenv("IMAP_USER")
    password = os.getenv("IMAP_PASSWORD")
    pairs = [("IMAP_HOST", host), ("IMAP_USER", user), ("IMAP_PASSWORD", password)]
    missing = [k for k, v in pairs if not v]
    if missing:
        raise RuntimeError(
            f"Missing required IMAP env vars: {', '.join(missing)}. "
            "Set IMAP_HOST, IMAP_USER, and IMAP_PASSWORD in your .env file."
        )
    return host, port, user, password  # type: ignore[return-value]


def fetch_unread(since: datetime | None = None) -> list[EmailSummary]:
    """Fetch unread emails from INBOX, optionally filtered by date."""
    host, port, user, password = _get_env_vars()

    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(user, password)
        imap.select("INBOX")

        criteria = ["UNSEEN"]
        if since is not None:
            date_str = since.strftime("%d-%b-%Y")
            criteria += ["SINCE", date_str]

        _status, data = imap.search(None, *criteria)
        if not data or not data[0]:
            return []

        summaries: list[EmailSummary] = []
        for uid in data[0].split():
            _status, msg_data = imap.fetch(uid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0]
            if not isinstance(raw, tuple):
                continue
            msg = email.message_from_bytes(raw[1])

            from_addr = _decode_header(msg.get("From"))
            subject = _decode_header(msg.get("Subject"))
            body = _get_plain_body(msg)[:500]

            date_str = msg.get("Date", "")
            try:
                from email.utils import parsedate_to_datetime

                timestamp = parsedate_to_datetime(date_str).astimezone(timezone.utc)
            except Exception:
                timestamp = datetime.now(timezone.utc)

            summaries.append(
                EmailSummary(
                    from_addr=from_addr,
                    subject=subject,
                    body_preview=body,
                    timestamp=timestamp,
                )
            )

        return summaries


@mcp.tool()
def imap_read() -> str:
    """Fetch unread emails from INBOX via IMAP.

    Returns a summary of unread messages. Only works when IMAP env vars are configured
    (IMAP_HOST, IMAP_USER, IMAP_PASSWORD).
    """
    try:
        emails = fetch_unread()
        if not emails:
            return "[No new emails]"
        lines = [f"[{len(emails)} new email(s):]"]
        for e in emails:
            lines.append(
                f"From: {e.from_addr}\nSubject: {e.subject}\n"
                f"Date: {e.timestamp.isoformat()}\n{e.body_preview}"
            )
        return "\n\n".join(lines)
    except Exception as exc:
        return f"[IMAP unavailable: {exc}]"


if __name__ == "__main__":
    mcp.run()
