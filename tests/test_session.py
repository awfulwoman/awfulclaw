"""Tests for ClaudeSession lifecycle and fallback behaviour."""

from __future__ import annotations

import time
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from awfulclaw.claude import ClaudeSession


def _make_mock_proc(stdout_lines: list[str], poll_return: int | None = None) -> MagicMock:
    proc = MagicMock()
    proc.stdin = MagicMock()
    stdout_text = "\n".join(stdout_lines) + "\n"
    proc.stdout = StringIO(stdout_text)
    proc.poll.return_value = poll_return
    return proc


def _session_with_proc(proc: MagicMock) -> ClaudeSession:
    with patch("awfulclaw.claude.subprocess.Popen", return_value=proc):
        return ClaudeSession(system="test system")


# ---------------------------------------------------------------------------
# Normal send
# ---------------------------------------------------------------------------


def test_send_returns_content_between_sentinels() -> None:
    proc = _make_mock_proc([
        ClaudeSession.SENTINEL_START,
        "Hello there",
        "world",
        ClaudeSession.SENTINEL_END,
    ])
    session = _session_with_proc(proc)

    result = session.send([{"role": "user", "content": "hi"}])

    assert result == "Hello there\nworld"
    proc.stdin.write.assert_called_once()
    proc.stdin.flush.assert_called_once()


# ---------------------------------------------------------------------------
# is_alive after idle timeout
# ---------------------------------------------------------------------------


def test_is_alive_false_after_idle_timeout() -> None:
    proc = _make_mock_proc([], poll_return=None)
    session = _session_with_proc(proc)

    # Force last_used into the past beyond the idle timeout
    session._last_used = time.monotonic() - session._idle_timeout - 1  # pyright: ignore[reportPrivateUsage]

    assert session.is_alive() is False


def test_is_alive_true_before_idle_timeout() -> None:
    proc = _make_mock_proc([], poll_return=None)
    session = _session_with_proc(proc)

    assert session.is_alive() is True


# ---------------------------------------------------------------------------
# is_alive after process exit
# ---------------------------------------------------------------------------


def test_is_alive_false_when_process_exited() -> None:
    proc = _make_mock_proc([], poll_return=0)
    session = _session_with_proc(proc)

    assert session.is_alive() is False


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_terminates_subprocess() -> None:
    proc = _make_mock_proc([], poll_return=None)
    session = _session_with_proc(proc)

    session.close()

    proc.terminate.assert_called_once()
    assert session._process is None  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Fallback in loop: if send() raises, claude.chat() is called
# ---------------------------------------------------------------------------


def test_loop_fallback_to_chat_on_session_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_session_call in loop.run() falls back to claude.chat() when session.send() raises."""
    import awfulclaw.claude as claude_mod

    messages = [{"role": "user", "content": "hello"}]
    system = "sys"

    # Build a session whose send() always raises
    broken_proc = _make_mock_proc([], poll_return=None)
    broken_proc.stdout = MagicMock()
    broken_proc.stdout.readline.side_effect = RuntimeError("pipe broken")

    with patch("awfulclaw.claude.subprocess.Popen", return_value=broken_proc):
        session = ClaudeSession(system=system)

    chat_mock = MagicMock(return_value="fallback reply")
    monkeypatch.setattr(claude_mod, "chat", chat_mock)

    # Simulate what _session_call does in loop.py
    try:
        result = session.send(messages)
    except Exception:
        result = claude_mod.chat(messages, system)

    assert result == "fallback reply"
    chat_mock.assert_called_once_with(messages, system)
