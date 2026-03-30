"""Tests for schedule condition evaluation and tag parsing via schedule module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from awfulclaw.modules.schedule._schedule import ScheduleModule, should_wake


def test_wake_true_when_condition_returns_wake_agent_true() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"wakeAgent": true}'
    with patch("awfulclaw.modules.schedule._schedule.subprocess.run", return_value=mock_result):
        assert should_wake("true-cmd") is True


def test_no_wake_when_condition_returns_wake_agent_false() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"wakeAgent": false}'
    with patch("awfulclaw.modules.schedule._schedule.subprocess.run", return_value=mock_result):
        assert should_wake("false-cmd") is False


def test_wake_true_when_wake_agent_missing_from_json() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "{}"
    with patch("awfulclaw.modules.schedule._schedule.subprocess.run", return_value=mock_result):
        assert should_wake("no-key-cmd") is True


def test_wake_true_on_nonzero_exit() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = '{"wakeAgent": false}'
    with patch("awfulclaw.modules.schedule._schedule.subprocess.run", return_value=mock_result):
        assert should_wake("fail-cmd") is True


def test_wake_true_on_timeout() -> None:
    import subprocess

    with patch(
        "awfulclaw.modules.schedule._schedule.subprocess.run",
        side_effect=subprocess.TimeoutExpired("cmd", 10),
    ):
        assert should_wake("slow-cmd") is True


def test_wake_true_on_invalid_json() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "not json"
    with patch("awfulclaw.modules.schedule._schedule.subprocess.run", return_value=mock_result):
        assert should_wake("bad-json-cmd") is True


# ---------------------------------------------------------------------------
# Schedule tag parsing — condition attribute
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory").mkdir()


def _dispatch_tag(tag: str) -> str:
    mod = ScheduleModule()
    skill_tag = mod.skill_tags[0]
    m = skill_tag.pattern.search(tag)
    assert m is not None
    return mod.dispatch(m, [], "")


def test_schedule_tag_with_condition_stores_condition() -> None:
    tag = (
        '<skill:schedule action="create" name="test" cron="0 * * * *"'
        ' condition="python check.py">Check things</skill:schedule>'
    )
    _dispatch_tag(tag)

    import awfulclaw.scheduler as sched

    schedules = sched.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].condition == "python check.py"


def test_schedule_tag_without_condition_stores_none() -> None:
    tag = (
        '<skill:schedule action="create" name="test" cron="0 * * * *">Check things</skill:schedule>'
    )
    _dispatch_tag(tag)

    import awfulclaw.scheduler as sched

    schedules = sched.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].condition is None
