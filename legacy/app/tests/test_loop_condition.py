"""Tests for schedule condition evaluation (should_wake) in awfulclaw.scheduler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from awfulclaw.scheduler import should_wake


def test_wake_true_when_condition_returns_wake_agent_true() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"wakeAgent": true}'
    with patch("awfulclaw.scheduler.subprocess.run", return_value=mock_result):
        assert should_wake("true-cmd") is True


def test_no_wake_when_condition_returns_wake_agent_false() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"wakeAgent": false}'
    with patch("awfulclaw.scheduler.subprocess.run", return_value=mock_result):
        assert should_wake("false-cmd") is False


def test_wake_true_when_wake_agent_missing_from_json() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "{}"
    with patch("awfulclaw.scheduler.subprocess.run", return_value=mock_result):
        assert should_wake("no-key-cmd") is True


def test_wake_true_on_nonzero_exit() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = '{"wakeAgent": false}'
    with patch("awfulclaw.scheduler.subprocess.run", return_value=mock_result):
        assert should_wake("fail-cmd") is True


def test_wake_true_on_timeout() -> None:
    import subprocess

    with patch(
        "awfulclaw.scheduler.subprocess.run",
        side_effect=subprocess.TimeoutExpired("cmd", 10),
    ):
        assert should_wake("slow-cmd") is True


def test_wake_true_on_invalid_json() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "not json"
    with patch("awfulclaw.scheduler.subprocess.run", return_value=mock_result):
        assert should_wake("bad-json-cmd") is True


# ---------------------------------------------------------------------------
# Schedule condition stored via scheduler (previously tested via module tag)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory").mkdir()


def test_schedule_condition_stored_correctly() -> None:
    """Schedules created via scheduler.py store their condition field."""
    import awfulclaw.scheduler as sched

    s = sched.Schedule.create(
        name="test", cron="0 * * * *", prompt="Check things", condition="python check.py"
    )
    sched.save_schedules([s])

    schedules = sched.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].condition == "python check.py"


def test_schedule_without_condition_stores_none() -> None:
    import awfulclaw.scheduler as sched

    s = sched.Schedule.create(name="test", cron="0 * * * *", prompt="Check things")
    sched.save_schedules([s])

    schedules = sched.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].condition is None
