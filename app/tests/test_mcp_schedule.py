"""Tests for MCP schedule server."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from awfulclaw.scheduler import Schedule
from awfulclaw_mcp.schedule import schedule_create, schedule_delete, schedule_list


def _make_schedule(name: str, cron: str = "0 8 * * *", prompt: str = "Hello") -> Schedule:
    return Schedule.create(name=name, cron=cron, prompt=prompt)


@pytest.fixture(autouse=True)
def _patch_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("awfulclaw_mcp.schedule.scheduler.load_schedules", lambda: [])
    monkeypatch.setattr("awfulclaw_mcp.schedule.scheduler.save_schedules", lambda s: None)


def test_create_cron_schedule() -> None:
    saved: list[list[Schedule]] = []
    _patch = "awfulclaw_mcp.schedule.scheduler.save_schedules"
    with patch(_patch, side_effect=lambda s: saved.append(list(s))):
        result = schedule_create("daily", "Say hello", cron="0 8 * * *")
    assert "created" in result
    assert "daily" in result
    assert saved[0][0].name == "daily"
    assert saved[0][0].cron == "0 8 * * *"


def test_create_at_schedule() -> None:
    saved: list[list[Schedule]] = []
    _patch = "awfulclaw_mcp.schedule.scheduler.save_schedules"
    with patch(_patch, side_effect=lambda s: saved.append(list(s))):
        result = schedule_create("reminder", "Check tasks", at="2026-12-31T09:00:00Z")
    assert "created" in result
    assert saved[0][0].fire_at is not None
    assert saved[0][0].fire_at.year == 2026


def test_create_updates_existing() -> None:
    existing = _make_schedule("daily")
    saved: list[list[Schedule]] = []
    _patch_save = "awfulclaw_mcp.schedule.scheduler.save_schedules"
    _patch_load = "awfulclaw_mcp.schedule.scheduler.load_schedules"
    with (
        patch(_patch_load, return_value=[existing]),
        patch(_patch_save, side_effect=lambda s: saved.append(list(s))),
    ):
        result = schedule_create("daily", "New prompt", cron="0 9 * * *")
    assert "updated" in result
    assert saved[0][0].prompt == "New prompt"
    assert saved[0][0].cron == "0 9 * * *"


def test_create_invalid_cron() -> None:
    result = schedule_create("bad", "Prompt", cron="not-a-cron")
    assert "invalid cron" in result.lower()


def test_create_invalid_at() -> None:
    result = schedule_create("bad", "Prompt", at="not-a-datetime")
    assert "invalid datetime" in result.lower()


def test_create_no_cron_or_at() -> None:
    result = schedule_create("bad", "Prompt")
    assert "must provide" in result.lower()


def test_delete_existing() -> None:
    existing = _make_schedule("daily")
    saved: list[list[Schedule]] = []
    _patch_save = "awfulclaw_mcp.schedule.scheduler.save_schedules"
    _patch_load = "awfulclaw_mcp.schedule.scheduler.load_schedules"
    with (
        patch(_patch_load, return_value=[existing]),
        patch(_patch_save, side_effect=lambda s: saved.append(list(s))),
    ):
        result = schedule_delete("daily")
    assert "deleted" in result
    assert saved[0] == []


def test_delete_not_found() -> None:
    result = schedule_delete("nonexistent")
    assert "not found" in result


def test_list_empty() -> None:
    result = schedule_list()
    assert "No schedules" in result


def test_list_with_schedules() -> None:
    schedules = [
        _make_schedule("daily", cron="0 8 * * *", prompt="Morning briefing"),
        _make_schedule("weekly", cron="0 10 * * 1", prompt="Weekly review"),
    ]
    with patch("awfulclaw_mcp.schedule.scheduler.load_schedules", return_value=schedules):
        result = schedule_list()
    assert "daily" in result
    assert "weekly" in result
    assert "0 8 * * *" in result


def test_list_one_off_shows_fire_at() -> None:
    fire_at = datetime(2026, 12, 31, 9, 0, tzinfo=timezone.utc)
    s = Schedule.create(name="reminder", prompt="Check in", fire_at=fire_at)
    with patch("awfulclaw_mcp.schedule.scheduler.load_schedules", return_value=[s]):
        result = schedule_list()
    assert "reminder" in result
    assert "2026-12-31" in result


def test_create_with_condition() -> None:
    saved: list[list[Schedule]] = []
    _patch = "awfulclaw_mcp.schedule.scheduler.save_schedules"
    with patch(_patch, side_effect=lambda s: saved.append(list(s))):
        result = schedule_create("cond", "Prompt", cron="*/5 * * * *", condition="check.sh")
    assert "created" in result
    assert saved[0][0].condition == "check.sh"
