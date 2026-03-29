"""Tests for scheduler.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from awfulclaw.scheduler import Schedule, get_due, load_schedules, save_schedules


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_load_returns_empty_for_missing_file() -> None:
    assert load_schedules() == []


def test_save_and_load_round_trip() -> None:
    s = Schedule.create(name="Daily", cron="0 9 * * *", prompt="Good morning!")
    save_schedules([s])
    loaded = load_schedules()
    assert len(loaded) == 1
    assert loaded[0].id == s.id
    assert loaded[0].name == s.name
    assert loaded[0].cron == s.cron
    assert loaded[0].prompt == s.prompt
    assert loaded[0].last_run is None


def test_save_round_trip_with_last_run() -> None:
    s = Schedule.create(name="Hourly", cron="0 * * * *", prompt="Check in")
    s.last_run = datetime(2026, 3, 29, 8, 0, tzinfo=timezone.utc)
    save_schedules([s])
    loaded = load_schedules()
    assert loaded[0].last_run == s.last_run


def test_get_due_no_last_run_returns_schedule() -> None:
    s = Schedule.create(name="Test", cron="0 9 * * *", prompt="Hello")
    now = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due


def test_get_due_already_ran_not_due() -> None:
    s = Schedule.create(name="Test", cron="0 9 * * *", prompt="Hello")
    s.last_run = datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc)
    # now is just 30 minutes after last_run — next run is tomorrow at 9am
    now = datetime(2026, 3, 29, 9, 30, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert due == []


def test_get_due_past_next_run() -> None:
    s = Schedule.create(name="Test", cron="0 9 * * *", prompt="Hello")
    s.last_run = datetime(2026, 3, 28, 9, 0, tzinfo=timezone.utc)
    # now is the next day at 10am — the 9am run was due
    now = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due
