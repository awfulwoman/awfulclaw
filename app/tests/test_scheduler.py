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
    assert loaded[0].created_at == s.created_at



def test_save_round_trip_with_last_run() -> None:
    s = Schedule.create(name="Hourly", cron="0 * * * *", prompt="Check in")
    s.last_run = datetime(2026, 3, 29, 8, 0, tzinfo=timezone.utc)
    save_schedules([s])
    loaded = load_schedules()
    assert loaded[0].last_run == s.last_run


def test_get_due_no_last_run_returns_schedule() -> None:
    s = Schedule(
        id="t1",
        name="Test",
        cron="0 9 * * *",
        prompt="Hello",
        created_at=datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc),
    )
    now = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due


def test_get_due_already_ran_not_due() -> None:
    s = Schedule(
        id="t3",
        name="Test",
        cron="0 9 * * *",
        prompt="Hello",
        created_at=datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc),
        last_run=datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc),
    )
    # now is just 30 minutes after last_run — next run is tomorrow at 9am
    now = datetime(2026, 3, 29, 9, 30, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert due == []


def test_get_due_past_next_run() -> None:
    s = Schedule(
        id="t2",
        name="Test",
        cron="0 9 * * *",
        prompt="Hello",
        created_at=datetime(2026, 3, 28, 0, 0, tzinfo=timezone.utc),
        last_run=datetime(2026, 3, 28, 9, 0, tzinfo=timezone.utc),
    )
    # now is the next day at 10am — the 9am run was due
    now = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due


def test_one_off_fires_when_due() -> None:
    fire_at = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    s = Schedule.create(name="Dentist", prompt="Dentist reminder", fire_at=fire_at)
    now = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due


def test_one_off_does_not_fire_before_time() -> None:
    fire_at = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    s = Schedule.create(name="Dentist", prompt="Dentist reminder", fire_at=fire_at)
    now = datetime(2026, 4, 1, 14, 59, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert due == []


def test_one_off_round_trip() -> None:
    fire_at = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    s = Schedule.create(name="Dentist", prompt="Dentist reminder", fire_at=fire_at)
    save_schedules([s])
    loaded = load_schedules()
    assert len(loaded) == 1
    assert loaded[0].fire_at == fire_at
    assert loaded[0].cron == ""


def test_get_due_no_catch_up_after_downtime() -> None:
    """3 missed hourly intervals: only 1 firing occurs, not 3."""
    # created 5 hours ago, runs hourly
    created = datetime(2026, 3, 29, 5, 0, tzinfo=timezone.utc)
    s = Schedule(
        id="x",
        name="Hourly",
        cron="0 * * * *",
        prompt="ping",
        created_at=created,
        last_run=datetime(2026, 3, 29, 6, 0, tzinfo=timezone.utc),  # fired at 6am
    )
    # restarted at 9:30am — 3 missed intervals (7, 8, 9am)
    now = datetime(2026, 3, 29, 9, 30, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due
    # simulate loop updating last_run and checking again — should not re-fire
    s.last_run = now
    due2 = get_due([s], now)
    assert due2 == []


def test_get_due_does_not_fire_within_same_interval() -> None:
    """After firing, schedule is not due again until next interval."""
    created = datetime(2026, 3, 29, 8, 0, tzinfo=timezone.utc)
    s = Schedule(
        id="y",
        name="Daily",
        cron="0 9 * * *",
        prompt="hi",
        created_at=created,
        last_run=datetime(2026, 3, 29, 9, 1, tzinfo=timezone.utc),
    )
    now = datetime(2026, 3, 29, 9, 30, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert due == []


def test_condition_round_trip() -> None:
    s = Schedule.create(name="Cond", cron="0 * * * *", prompt="Check", condition="python check.py")
    assert s.condition == "python check.py"
    save_schedules([s])
    loaded = load_schedules()
    assert loaded[0].condition == "python check.py"


def test_condition_none_round_trip() -> None:
    s = Schedule.create(name="NoCond", cron="0 * * * *", prompt="Check")
    assert s.condition is None
    save_schedules([s])
    loaded = load_schedules()
    assert loaded[0].condition is None


def test_silent_default_is_false() -> None:
    s = Schedule.create(name="Loud", cron="0 9 * * *", prompt="Hello")
    assert s.silent is False


def test_silent_round_trip() -> None:
    s = Schedule.create(name="Silent", cron="0 9 * * *", prompt="Shh", silent=True)
    save_schedules([s])
    loaded = load_schedules()
    assert loaded[0].silent is True


def test_non_silent_round_trip() -> None:
    s = Schedule.create(name="Loud", cron="0 9 * * *", prompt="Hi", silent=False)
    save_schedules([s])
    loaded = load_schedules()
    assert loaded[0].silent is False



def test_get_due_fires_on_next_interval() -> None:
    """After last_run, fires again on the next cron interval."""
    created = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)
    s = Schedule(
        id="z",
        name="Daily",
        cron="0 9 * * *",
        prompt="hi",
        created_at=created,
        last_run=datetime(2026, 3, 29, 9, 1, tzinfo=timezone.utc),
    )
    now = datetime(2026, 3, 30, 9, 5, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due
