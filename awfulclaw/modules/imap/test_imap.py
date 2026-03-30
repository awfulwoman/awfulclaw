"""Tests for the imap module."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from awfulclaw.modules.imap import EmailSummary, fetch_unread


def _make_raw_email(
    from_addr: str = "sender@example.com",
    subject: str = "Hello",
    body: str = "This is the body.",
    date: str = "Mon, 01 Jan 2024 12:00:00 +0000",
) -> bytes:
    msg = Message()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Date"] = date
    msg.set_payload(body)
    return msg.as_bytes()


def _setup_mock_imap(mock_imap_cls: MagicMock, raw_emails: list[bytes]) -> MagicMock:
    mock_conn = MagicMock()
    mock_imap_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_imap_cls.return_value.__exit__ = MagicMock(return_value=False)

    uid_list = b" ".join(str(i + 1).encode() for i in range(len(raw_emails)))
    mock_conn.search.return_value = ("OK", [uid_list])

    fetch_results = [("OK", [(b"1 (RFC822 {100})", raw)]) for raw in raw_emails]
    mock_conn.fetch.side_effect = fetch_results
    return mock_conn


def test_fetch_unread_returns_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")

    raw = _make_raw_email(
        from_addr="alice@example.com",
        subject="Test Subject",
        body="Hello world, this is a test email.",
        date="Mon, 01 Jan 2024 12:00:00 +0000",
    )

    with patch("imaplib.IMAP4_SSL") as mock_cls:
        _setup_mock_imap(mock_cls, [raw])
        results = fetch_unread()

    assert len(results) == 1
    s = results[0]
    assert isinstance(s, EmailSummary)
    assert "alice@example.com" in s.from_addr
    assert s.subject == "Test Subject"
    assert "Hello world" in s.body_preview
    assert s.timestamp.tzinfo is not None


def test_fetch_unread_empty_inbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")

    with patch("imaplib.IMAP4_SSL") as mock_cls:
        mock_conn = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.search.return_value = ("OK", [b""])
        results = fetch_unread()

    assert results == []


def test_fetch_unread_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.delenv("IMAP_USER", raising=False)
    monkeypatch.delenv("IMAP_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="IMAP_HOST"):
        fetch_unread()


def test_fetch_unread_with_since_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")

    raw = _make_raw_email()
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)

    with patch("imaplib.IMAP4_SSL") as mock_cls:
        mock_conn = _setup_mock_imap(mock_cls, [raw])
        fetch_unread(since=since)

    call_args = mock_conn.search.call_args
    criteria = call_args[0]
    assert "SINCE" in criteria


def test_imap_module_is_available_false_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from awfulclaw.modules.imap._imap import ImapModule

    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.delenv("IMAP_USER", raising=False)
    monkeypatch.delenv("IMAP_PASSWORD", raising=False)
    mod = ImapModule()
    assert mod.is_available() is False


def test_imap_module_is_available_true_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from awfulclaw.modules.imap._imap import ImapModule

    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    mod = ImapModule()
    assert mod.is_available() is True


def test_imap_module_dispatch_formats_emails(monkeypatch: pytest.MonkeyPatch) -> None:
    from awfulclaw.modules.imap._imap import ImapModule

    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")

    raw = _make_raw_email(
        from_addr="bob@example.com",
        subject="Important",
        body="Read this!",
    )
    mod = ImapModule()
    tag = mod.skill_tags[0]
    m = tag.pattern.match("<skill:imap/>")
    assert m is not None

    with patch("imaplib.IMAP4_SSL") as mock_cls:
        _setup_mock_imap(mock_cls, [raw])
        result = mod.dispatch(m, [], "")

    assert "bob@example.com" in result
    assert "Important" in result
    assert "Read this!" in result


def test_imap_module_dispatch_no_emails(monkeypatch: pytest.MonkeyPatch) -> None:
    from awfulclaw.modules.imap._imap import ImapModule

    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")

    mod = ImapModule()
    tag = mod.skill_tags[0]
    m = tag.pattern.match("<skill:imap/>")
    assert m is not None

    with patch("imaplib.IMAP4_SSL") as mock_cls:
        mock_conn = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.search.return_value = ("OK", [b""])
        result = mod.dispatch(m, [], "")

    assert "No new emails" in result


def test_create_module() -> None:
    from awfulclaw.modules.imap import create_module

    mod = create_module()
    assert mod.name == "imap"
    assert len(mod.skill_tags) == 1
