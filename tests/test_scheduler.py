"""Tests for agent/scheduler.py."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.bus import Bus, ScheduleEvent
from agent.scheduler import Scheduler, _earliest_due
from agent.store import Schedule


def _make_schedule(
    *,
    id: str = "s1",
    name: str = "test",
    cron: str | None = None,
    fire_at: str | None = None,
    prompt: str = "do something",
    silent: bool = False,
    tz: str = "",
    last_run: str | None = None,
) -> Schedule:
    return Schedule(
        id=id,
        name=name,
        cron=cron,
        fire_at=fire_at,
        prompt=prompt,
        silent=silent,
        tz=tz,
        created_at="2026-01-01T00:00:00+00:00",
        last_run=last_run,
    )


# --- _earliest_due ---


def test_earliest_due_empty() -> None:
    best, ft = _earliest_due([])
    assert best is None
    assert ft is None


def test_earliest_due_one_shot_in_future() -> None:
    future = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
    s = _make_schedule(fire_at=future)
    best, ft = _earliest_due([s])
    assert best is s
    assert ft is not None


def test_earliest_due_one_shot_in_past_unrun() -> None:
    """Past one-shot with no last_run is overdue and should be returned."""
    past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
    s = _make_schedule(fire_at=past, last_run=None)
    best, ft = _earliest_due([s])
    assert best is s
    assert ft is not None


def test_earliest_due_one_shot_already_ran() -> None:
    """Past one-shot that already ran (last_run set) should be skipped."""
    past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
    s = _make_schedule(fire_at=past, last_run="2026-01-01T00:00:00+00:00")
    best, ft = _earliest_due([s])
    assert best is None
    assert ft is None


def test_earliest_due_picks_soonest() -> None:
    now = datetime.now(tz=timezone.utc)
    sooner = (now + timedelta(minutes=5)).isoformat()
    later = (now + timedelta(hours=2)).isoformat()
    s1 = _make_schedule(id="s1", fire_at=sooner)
    s2 = _make_schedule(id="s2", fire_at=later)
    best, ft = _earliest_due([s1, s2])
    assert best is s1


# --- Scheduler.run ---


@pytest.mark.asyncio
async def test_fires_due_schedule() -> None:
    """Scheduler posts ScheduleEvent when a schedule is due."""
    bus = Bus()

    # Schedule overdue by 1 second
    past = (datetime.now(tz=timezone.utc) - timedelta(seconds=1)).isoformat()
    schedule = _make_schedule(fire_at=past)

    call_count = 0

    async def list_schedules() -> list[Schedule]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [schedule]
        # Return empty after first fire so scheduler sleeps for 60s (easy to cancel)
        return []

    store = MagicMock()
    store.list_schedules = list_schedules
    store.update_schedule_last_run = AsyncMock()

    scheduler = Scheduler()
    task = asyncio.create_task(scheduler.run(bus, store))

    # Give the scheduler time to complete its first iteration (delay=0, fires immediately)
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    # Verify ScheduleEvent was posted to the bus queue
    assert not bus._queue.empty(), "ScheduleEvent was not posted to bus"
    event = bus._queue.get_nowait()
    assert isinstance(event, ScheduleEvent)
    assert event.schedule is schedule

    # Verify last_run was updated
    store.update_schedule_last_run.assert_called_once()
    call_id, call_last_run = store.update_schedule_last_run.call_args[0]
    assert call_id == schedule.id
    assert call_last_run is not None


@pytest.mark.asyncio
async def test_skips_not_yet_due() -> None:
    """Scheduler does not fire a schedule with fire_time in the future."""
    bus = Bus()

    # Schedule due in 1 hour — should NOT fire
    future = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
    schedule = _make_schedule(fire_at=future)

    store = MagicMock()
    store.list_schedules = AsyncMock(return_value=[schedule])
    store.update_schedule_last_run = AsyncMock()

    scheduler = Scheduler()

    # Scheduler sleeps for ~3600s waiting for the future schedule; cancel quickly
    task = asyncio.create_task(scheduler.run(bus, store))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert bus._queue.empty(), "ScheduleEvent was posted but should not have been"
    store.update_schedule_last_run.assert_not_called()


@pytest.mark.asyncio
async def test_wake_interrupts_sleep() -> None:
    """wake() causes the scheduler to re-evaluate and fire a newly due schedule."""
    bus = Bus()

    past = (datetime.now(tz=timezone.utc) - timedelta(seconds=1)).isoformat()
    due_schedule = _make_schedule(fire_at=past)

    call_count = 0

    async def list_schedules() -> list[Schedule]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []  # nothing due on first check; scheduler sleeps for 60s
        if call_count == 2:
            return [due_schedule]  # schedule appears after wake()
        return []  # subsequent calls: empty so scheduler sleeps again

    store = MagicMock()
    store.list_schedules = list_schedules
    store.update_schedule_last_run = AsyncMock()

    scheduler = Scheduler()
    task = asyncio.create_task(scheduler.run(bus, store))

    # Let scheduler enter its 60s sleep, then wake it
    await asyncio.sleep(0.05)
    assert call_count >= 1, "scheduler never called list_schedules"

    scheduler.wake()

    # Give it time to process the second iteration
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert call_count >= 2, "scheduler did not re-evaluate after wake()"
    assert not bus._queue.empty(), "ScheduleEvent was not posted after wake()"
    event = bus._queue.get_nowait()
    assert isinstance(event, ScheduleEvent)
    assert event.schedule is due_schedule
