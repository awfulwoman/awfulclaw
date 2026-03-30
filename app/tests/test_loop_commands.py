"""Tests for _handle_slash_command in loop.py."""

from __future__ import annotations

from unittest.mock import patch

from awfulclaw.loop import handle_slash_command as _handle_slash_command
from awfulclaw.scheduler import Schedule

# ---------------------------------------------------------------------------
# /schedules
# ---------------------------------------------------------------------------


def test_schedules_returns_list() -> None:
    sched = Schedule.create(name="morning", cron="0 8 * * *", prompt="Good morning check")
    with patch("awfulclaw.loop.scheduler.load_schedules", return_value=[sched]):
        result = _handle_slash_command("/schedules")
    assert result is not None
    assert "morning" in result
    assert "0 8 * * *" in result
    assert "Good morning check" in result


def test_schedules_empty() -> None:
    with patch("awfulclaw.loop.scheduler.load_schedules", return_value=[]):
        result = _handle_slash_command("/schedules")
    assert result == "No schedules."


def test_schedules_prompt_truncated() -> None:
    long_prompt = "A" * 100
    sched = Schedule.create(name="test", cron="* * * * *", prompt=long_prompt)
    with patch("awfulclaw.loop.scheduler.load_schedules", return_value=[sched]):
        result = _handle_slash_command("/schedules")
    assert result is not None
    assert "…" in result


# ---------------------------------------------------------------------------
# unknown command
# ---------------------------------------------------------------------------


def test_unknown_command_lists_available() -> None:
    result = _handle_slash_command("/foo")
    assert result is not None
    assert "/schedules" in result


# ---------------------------------------------------------------------------
# non-command returns None
# ---------------------------------------------------------------------------


def test_non_command_returns_none() -> None:
    assert _handle_slash_command("hello world") is None
    assert _handle_slash_command("") is None
