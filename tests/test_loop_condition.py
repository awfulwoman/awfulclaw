"""Tests for schedule condition evaluation (_should_wake) in loop.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from awfulclaw.loop import _should_wake


def test_wake_true_when_condition_returns_wake_agent_true() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"wakeAgent": true}'
    with patch("awfulclaw.loop.subprocess.run", return_value=mock_result):
        assert _should_wake("true-cmd") is True


def test_no_wake_when_condition_returns_wake_agent_false() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"wakeAgent": false}'
    with patch("awfulclaw.loop.subprocess.run", return_value=mock_result):
        assert _should_wake("false-cmd") is False


def test_wake_true_when_wake_agent_missing_from_json() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{}'
    with patch("awfulclaw.loop.subprocess.run", return_value=mock_result):
        assert _should_wake("no-key-cmd") is True


def test_wake_true_on_nonzero_exit() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = '{"wakeAgent": false}'
    with patch("awfulclaw.loop.subprocess.run", return_value=mock_result):
        assert _should_wake("fail-cmd") is True


def test_wake_true_on_timeout() -> None:
    import subprocess
    with patch("awfulclaw.loop.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
        assert _should_wake("slow-cmd") is True


def test_wake_true_on_invalid_json() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "not json"
    with patch("awfulclaw.loop.subprocess.run", return_value=mock_result):
        assert _should_wake("bad-json-cmd") is True
