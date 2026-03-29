"""Tests for _evaluate_condition in loop.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from awfulclaw.loop import _evaluate_condition


def _mock_run(stdout: str = "", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


def test_wake_agent_true_proceeds() -> None:
    with patch("awfulclaw.loop.subprocess.run", return_value=_mock_run('{"wakeAgent": true}')):
        assert _evaluate_condition("true", "test") is True


def test_wake_agent_false_suppresses() -> None:
    with patch("awfulclaw.loop.subprocess.run", return_value=_mock_run('{"wakeAgent": false}')):
        assert _evaluate_condition("false", "test") is False


def test_wake_agent_missing_defaults_to_proceed() -> None:
    with patch("awfulclaw.loop.subprocess.run", return_value=_mock_run("{}")):
        assert _evaluate_condition("cmd", "test") is True


def test_nonzero_exit_proceeds() -> None:
    with patch("awfulclaw.loop.subprocess.run", return_value=_mock_run("", returncode=1)):
        assert _evaluate_condition("bad", "test") is True


def test_timeout_proceeds() -> None:
    import subprocess

    with patch("awfulclaw.loop.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
        assert _evaluate_condition("slow", "test") is True


def test_invalid_json_proceeds() -> None:
    with patch("awfulclaw.loop.subprocess.run", return_value=_mock_run("not-json")):
        assert _evaluate_condition("bad-json", "test") is True
