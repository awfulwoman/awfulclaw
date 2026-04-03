"""imap MCP server — read-only email access tools.

Exposes:
  email_unread(limit?)         — list unread emails (UID, subject, from, date)
  email_read(uid)              — fetch full email body by UID
  email_search(query)          — search mailbox with IMAP SEARCH query string

Email bodies are wrapped in <untrusted-content> tags to signal that content
originates from an external, potentially adversarial source.

Configure via env vars:
  IMAP_HOST       — IMAP server hostname
  IMAP_PORT       — IMAP port (default 993)
  IMAP_USERNAME   — login username
  IMAP_PASSWORD   — login password
"""
from __future__ import annotations

import email
import email.header
import email.message
import os
from typing import Optional

import aioimaplib  # type: ignore[import-untyped]
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("imap")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _get_settings() -> tuple[str, int, str, str]:
    host = os.environ.get("IMAP_HOST", "")
    port = int(os.environ.get("IMAP_PORT", "993"))
    username = os.environ.get("IMAP_USERNAME", "")
    password = os.environ.get("IMAP_PASSWORD", "")
    return host, port, username, password


# ---------------------------------------------------------------------------
# IMAP connection helper
# ---------------------------------------------------------------------------


async def _connect() -> aioimaplib.IMAP4_SSL:
    host, port, username, password = _get_settings()
    if not host or not username or not password:
        raise ValueError("IMAP credentials not configured (IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD)")
    client = aioimaplib.IMAP4_SSL(host=host, port=port, timeout=15)
    await client.wait_hello_from_server()
    await client.login(username, password)
    await client.select("INBOX")
    return client


# ---------------------------------------------------------------------------
# Email parsing helpers
# ---------------------------------------------------------------------------


def _decode_header_value(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    parts = email.header.decode_header(raw)
    decoded_parts: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def _extract_body(msg: email.message.Message) -> str:
    """Extract plain-text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                if isinstance(payload, bytes):
                    return payload.decode(charset, errors="replace")
        # Fallback: return first part's payload
        first = msg.get_payload(0)
        if isinstance(first, email.message.Message):
            payload = first.get_payload(decode=True)
            if isinstance(payload, bytes):
                return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload) if payload else ""


def _wrap_untrusted(body: str, sender: str) -> str:
    return f'<untrusted-content source="email" from="{sender}">\n{body}\n</untrusted-content>'


def _parse_envelope(uid: str, raw_headers: bytes) -> dict:
    """Parse envelope fields from raw header bytes."""
    msg = email.message_from_bytes(raw_headers)
    return {
        "uid": uid,
        "subject": _decode_header_value(msg.get("Subject")),
        "from": _decode_header_value(msg.get("From")),
        "date": _decode_header_value(msg.get("Date")),
    }


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def email_unread(limit: Optional[int] = 20) -> list[dict]:
    """List unread emails from INBOX.

    limit: max number of emails to return (default 20, newest first)

    Returns a list of dicts with uid, subject, from, date fields.
    """
    try:
        client = await _connect()
    except ValueError as exc:
        return [{"error": str(exc)}]

    try:
        _, data = await client.search("UNSEEN")
        uid_list_raw = data[0] if data else b""
        if isinstance(uid_list_raw, bytes):
            uid_str = uid_list_raw.decode()
        else:
            uid_str = str(uid_list_raw)

        uids = uid_str.split() if uid_str.strip() else []
        if not uids:
            return []

        # Newest first, apply limit
        uids = uids[-limit:] if limit else uids
        uids = list(reversed(uids))

        results: list[dict] = []
        for uid in uids:
            _, msg_data = await client.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            raw = msg_data[1] if len(msg_data) > 1 else b""
            if isinstance(raw, (bytes, bytearray)):
                results.append(_parse_envelope(uid, bytes(raw)))
        return results
    finally:
        await client.logout()


@mcp.tool()
async def email_read(uid: str) -> str:
    """Fetch the full body of an email by UID.

    uid: the email UID (from email_unread or email_search)

    Returns the email body wrapped in <untrusted-content> tags.
    """
    try:
        client = await _connect()
    except ValueError as exc:
        return f"Error: {exc}"

    try:
        _, msg_data = await client.fetch(uid, "(RFC822)")
        raw = msg_data[1] if len(msg_data) > 1 else b""
        if not raw:
            return f"Error: message {uid!r} not found"

        if not isinstance(raw, (bytes, bytearray)):
            return f"Error: unexpected data type for message {uid!r}"

        msg = email.message_from_bytes(bytes(raw))
        sender = _decode_header_value(msg.get("From"))
        body = _extract_body(msg)
        return _wrap_untrusted(body, sender)
    finally:
        await client.logout()


@mcp.tool()
async def email_search(query: str) -> list[dict]:
    """Search emails using an IMAP SEARCH query.

    query: IMAP search criteria (e.g. 'FROM "alice@example.com"', 'SUBJECT "invoice"',
           'SINCE 01-Jan-2025', 'TEXT "meeting"')

    Returns a list of dicts with uid, subject, from, date fields.
    """
    try:
        client = await _connect()
    except ValueError as exc:
        return [{"error": str(exc)}]

    try:
        _, data = await client.search(query)
        uid_list_raw = data[0] if data else b""
        if isinstance(uid_list_raw, bytes):
            uid_str = uid_list_raw.decode()
        else:
            uid_str = str(uid_list_raw)

        uids = uid_str.split() if uid_str.strip() else []
        if not uids:
            return []

        results: list[dict] = []
        for uid in uids:
            _, msg_data = await client.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            raw = msg_data[1] if len(msg_data) > 1 else b""
            if isinstance(raw, (bytes, bytearray)):
                results.append(_parse_envelope(uid, bytes(raw)))
        return results
    finally:
        await client.logout()


if __name__ == "__main__":
    mcp.run()
