"""Unit tests for agent/mcp/imap.py — fully mocked IMAP client."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.mcp.imap as imap_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_header_bytes(subject: str, from_: str, date: str = "Thu, 1 Jan 2026 12:00:00 +0000") -> bytes:
    return f"Subject: {subject}\r\nFrom: {from_}\r\nDate: {date}\r\n\r\n".encode()


def _make_rfc822_bytes(subject: str, from_: str, body: str) -> bytes:
    return (
        f"Subject: {subject}\r\nFrom: {from_}\r\nDate: Thu, 1 Jan 2026 12:00:00 +0000\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}"
    ).encode()


def _mock_client(search_uids: list[str], fetch_payloads: dict[str, bytes]) -> MagicMock:
    """Build a mock aioimaplib client for given UID list and per-UID fetch payloads."""
    client = MagicMock()
    client.wait_hello_from_server = AsyncMock()
    client.login = AsyncMock()
    client.select = AsyncMock()
    client.logout = AsyncMock()

    uid_bytes = " ".join(search_uids).encode()

    async def fake_search(query: str) -> tuple[str, list[bytes]]:
        return ("OK", [uid_bytes])

    client.search = AsyncMock(side_effect=fake_search)

    async def fake_fetch(uid: str, parts: str) -> tuple[str, list[bytes]]:
        payload = fetch_payloads.get(uid, b"")
        return ("OK", [b"", payload])

    client.fetch = AsyncMock(side_effect=fake_fetch)

    return client


# ---------------------------------------------------------------------------
# Tests: email_unread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_unread_returns_list() -> None:
    header1 = _make_header_bytes("Hello world", "alice@example.com")
    header2 = _make_header_bytes("Invoice #42", "billing@corp.com")

    mock_client = _mock_client(
        search_uids=["1", "2"],
        fetch_payloads={"1": header1, "2": header2},
    )

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_unread(limit=20)

    assert len(result) == 2
    subjects = {r["subject"] for r in result}
    assert "Hello world" in subjects
    assert "Invoice #42" in subjects


@pytest.mark.asyncio
async def test_email_unread_empty_inbox() -> None:
    mock_client = _mock_client(search_uids=[], fetch_payloads={})

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_unread()

    assert result == []


@pytest.mark.asyncio
async def test_email_unread_respects_limit() -> None:
    # 5 UIDs, limit=3 — should return only 3
    headers = {str(i): _make_header_bytes(f"Subject {i}", f"user{i}@x.com") for i in range(1, 6)}
    mock_client = _mock_client(
        search_uids=[str(i) for i in range(1, 6)],
        fetch_payloads=headers,
    )

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_unread(limit=3)

    assert len(result) == 3


@pytest.mark.asyncio
async def test_email_unread_no_credentials() -> None:
    with patch("agent.mcp.imap._get_settings", return_value=("", 993, "", "")):
        result = await imap_module.email_unread()

    assert len(result) == 1
    assert "error" in result[0]


# ---------------------------------------------------------------------------
# Tests: email_read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_read_wraps_in_untrusted_content() -> None:
    raw = _make_rfc822_bytes("Test subject", "bob@example.com", "This is the email body.")
    mock_client = _mock_client(search_uids=[], fetch_payloads={"42": raw})

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_read("42")

    assert '<untrusted-content source="email"' in result
    assert 'from="bob@example.com"' in result
    assert "This is the email body." in result
    assert "</untrusted-content>" in result


@pytest.mark.asyncio
async def test_email_read_message_not_found() -> None:
    mock_client = _mock_client(search_uids=[], fetch_payloads={})

    # fetch returns empty payload
    async def fake_fetch(uid: str, parts: str) -> tuple[str, list[bytes]]:
        return ("OK", [b"", b""])

    mock_client.fetch = AsyncMock(side_effect=fake_fetch)

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_read("999")

    assert "Error" in result
    assert "not found" in result


@pytest.mark.asyncio
async def test_email_read_no_credentials() -> None:
    with patch("agent.mcp.imap._get_settings", return_value=("", 993, "", "")):
        result = await imap_module.email_read("1")

    assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# Tests: email_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_search_returns_results() -> None:
    header = _make_header_bytes("Meeting notes", "boss@corp.com")
    mock_client = _mock_client(search_uids=["7"], fetch_payloads={"7": header})

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_search('SUBJECT "Meeting"')

    assert len(result) == 1
    assert result[0]["subject"] == "Meeting notes"
    assert result[0]["from"] == "boss@corp.com"
    assert result[0]["uid"] == "7"


@pytest.mark.asyncio
async def test_email_search_no_results() -> None:
    mock_client = _mock_client(search_uids=[], fetch_payloads={})

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_search('FROM "nobody@void.com"')

    assert result == []


@pytest.mark.asyncio
async def test_email_search_no_credentials() -> None:
    with patch("agent.mcp.imap._get_settings", return_value=("", 993, "", "")):
        result = await imap_module.email_search("ALL")

    assert len(result) == 1
    assert "error" in result[0]


# ---------------------------------------------------------------------------
# Tests: untrusted content framing
# ---------------------------------------------------------------------------


def test_wrap_untrusted_format() -> None:
    result = imap_module._wrap_untrusted("body text", "alice@example.com")
    assert result == '<untrusted-content source="email" from="alice@example.com">\nbody text\n</untrusted-content>'


# ---------------------------------------------------------------------------
# Tests: bulk-header extraction in email_unread
# ---------------------------------------------------------------------------


def _make_bulk_header_bytes(subject: str, from_: str, extra_headers: dict[str, str]) -> bytes:
    lines = [f"Subject: {subject}", f"From: {from_}", "Date: Thu, 1 Jan 2026 12:00:00 +0000"]
    for k, v in extra_headers.items():
        lines.append(f"{k}: {v}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


@pytest.mark.asyncio
async def test_email_unread_includes_list_unsubscribe_header() -> None:
    header = _make_bulk_header_bytes(
        "Weekly deals", "shop@example.com",
        {"List-Unsubscribe": "<mailto:unsub@example.com>"}
    )
    mock_client = _mock_client(search_uids=["10"], fetch_payloads={"10": header})

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_unread(limit=20)

    assert len(result) == 1
    assert result[0]["list_unsubscribe"] == "<mailto:unsub@example.com>"


@pytest.mark.asyncio
async def test_email_unread_includes_precedence_header() -> None:
    header = _make_bulk_header_bytes(
        "System alert", "noreply@system.com",
        {"Precedence": "bulk"}
    )
    mock_client = _mock_client(search_uids=["11"], fetch_payloads={"11": header})

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_unread(limit=20)

    assert result[0]["precedence"] == "bulk"


@pytest.mark.asyncio
async def test_email_unread_bulk_headers_empty_when_absent() -> None:
    header = _make_header_bytes("Hi there", "friend@example.com")
    mock_client = _mock_client(search_uids=["12"], fetch_payloads={"12": header})

    with patch("agent.mcp.imap._connect", return_value=mock_client):
        result = await imap_module.email_unread(limit=20)

    assert result[0]["list_unsubscribe"] == ""
    assert result[0]["precedence"] == ""
    assert result[0]["auto_submitted"] == ""
