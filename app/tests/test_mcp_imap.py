"""Tests for MCP imap_read server."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from awfulclaw_mcp.imap import EmailSummary, imap_read


def _make_email(
    from_addr: str = "sender@example.com",
    subject: str = "Test Subject",
    body_preview: str = "Hello there",
    timestamp: datetime | None = None,
) -> EmailSummary:
    if timestamp is None:
        timestamp = datetime(2026, 3, 30, 10, 0, 0, tzinfo=timezone.utc)
    return EmailSummary(
        from_addr=from_addr,
        subject=subject,
        body_preview=body_preview,
        timestamp=timestamp,
    )


def test_imap_read_no_emails() -> None:
    with patch("awfulclaw_mcp.imap.fetch_unread", return_value=[]):
        output = imap_read()
    assert "No new emails" in output


def test_imap_read_single_email() -> None:
    email = _make_email(subject="Hello", from_addr="alice@example.com", body_preview="Hi!")
    with patch("awfulclaw_mcp.imap.fetch_unread", return_value=[email]):
        output = imap_read()
    assert "1 new email" in output
    assert "alice@example.com" in output
    assert "Hello" in output
    assert "Hi!" in output


def test_imap_read_multiple_emails() -> None:
    emails = [
        _make_email(subject="First"),
        _make_email(subject="Second"),
        _make_email(subject="Third"),
    ]
    with patch("awfulclaw_mcp.imap.fetch_unread", return_value=emails):
        output = imap_read()
    assert "3 new email" in output
    assert "First" in output
    assert "Second" in output
    assert "Third" in output


def test_imap_read_includes_timestamp() -> None:
    ts = datetime(2026, 1, 15, 9, 30, 0, tzinfo=timezone.utc)
    email = _make_email(timestamp=ts)
    with patch("awfulclaw_mcp.imap.fetch_unread", return_value=[email]):
        output = imap_read()
    assert "2026-01-15" in output


def test_imap_read_handles_exception() -> None:
    with patch(
        "awfulclaw_mcp.imap.fetch_unread",
        side_effect=RuntimeError("Connection refused"),
    ):
        output = imap_read()
    assert "unavailable" in output.lower()
    assert "Connection refused" in output


def test_imap_read_calls_fetch_unread() -> None:
    with patch("awfulclaw_mcp.imap.fetch_unread", return_value=[]) as mock_fetch:
        imap_read()
        mock_fetch.assert_called_once_with()
