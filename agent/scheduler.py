"""Scheduler: sleeps until the next due schedule and fires ScheduleEvents."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.cron import next_fire_time

if TYPE_CHECKING:
    from agent.bus import Bus
    from agent.store import Schedule, Store


class Scheduler:
    def __init__(self) -> None:
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Signal the scheduler to re-evaluate (called by Store on schedule changes)."""
        self._wake.set()

    async def run(self, bus: "Bus", store: "Store") -> None:
        from agent.bus import ScheduleEvent

        while True:
            schedules = await store.list_schedules()
            next_due, fire_time = _earliest_due(schedules)

            if fire_time is not None:
                delay = max(0.0, (fire_time - datetime.now(tz=timezone.utc)).total_seconds())
            else:
                delay = 60.0

            self._wake.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=delay)

            if next_due is not None and fire_time is not None:
                now = datetime.now(tz=timezone.utc)
                if now >= fire_time:
                    await bus.post(ScheduleEvent(schedule=next_due))
                    await store.update_schedule_last_run(next_due.id, now.isoformat())


def _earliest_due(schedules: list["Schedule"]) -> tuple["Schedule | None", datetime | None]:
    """Return the schedule with the earliest next fire time and that fire time.

    For one-shot schedules with a past fire_at that haven't run (last_run is None),
    the past fire_at is returned as the fire_time so the scheduler fires them immediately.
    """
    best: "Schedule | None" = None
    best_time: datetime | None = None

    for schedule in schedules:
        ft = _schedule_fire_time(schedule)
        if ft is None:
            continue
        if best_time is None or ft < best_time:
            best = schedule
            best_time = ft

    return best, best_time


def _schedule_fire_time(schedule: "Schedule") -> datetime | None:
    """Return the fire time for a schedule, or None if it should not run."""
    # One-shot schedule
    if schedule.cron is None and schedule.fire_at is not None:
        if schedule.last_run is not None:
            return None  # already ran
        try:
            dt = datetime.fromisoformat(schedule.fire_at)
            if dt.tzinfo is None:
                zone_name = schedule.tz
                from zoneinfo import ZoneInfo
                zone = ZoneInfo(zone_name) if zone_name else timezone.utc
                dt = dt.replace(tzinfo=zone)
            return dt  # may be past (overdue) or future; either is valid
        except (ValueError, Exception):
            return None

    # Recurring cron schedule
    try:
        return next_fire_time(cron=schedule.cron, fire_at=schedule.fire_at, tz=schedule.tz)
    except (ValueError, Exception):
        return None
