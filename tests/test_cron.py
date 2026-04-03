"""Tests for agent/cron.py."""

from datetime import datetime, timezone, timedelta

import pytest

from agent.cron import next_fire_time


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dt(*args, tz=timezone.utc) -> datetime:
    return datetime(*args, tzinfo=tz)


UTC = timezone.utc


# ---------------------------------------------------------------------------
# fire_at (one-shot) schedules
# ---------------------------------------------------------------------------

class TestFireAt:
    def test_future_fire_at_returns_datetime(self):
        after = dt(2026, 1, 1, 12, 0, 0)
        fire = dt(2026, 1, 1, 13, 0, 0)
        result = next_fire_time(fire_at=fire.isoformat(), after=after)
        assert result == fire

    def test_past_fire_at_returns_none(self):
        after = dt(2026, 1, 1, 14, 0, 0)
        fire = dt(2026, 1, 1, 13, 0, 0)
        result = next_fire_time(fire_at=fire.isoformat(), after=after)
        assert result is None

    def test_fire_at_naive_string_uses_tz(self):
        """Naive fire_at string is interpreted in the schedule's timezone."""
        from zoneinfo import ZoneInfo
        after = dt(2026, 6, 1, 7, 0, 0)  # UTC 07:00
        # Berlin is UTC+2 in summer — naive "10:00" means UTC 08:00
        result = next_fire_time(
            fire_at="2026-06-01T10:00:00",
            tz="Europe/Berlin",
            after=after,
        )
        assert result is not None
        # Result should be UTC 08:00
        assert result == datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC)

    def test_fire_at_with_offset_preserved(self):
        """fire_at with explicit offset is used as-is."""
        fire = "2026-03-15T09:30:00+05:00"
        after = dt(2026, 3, 15, 0, 0, 0)
        result = next_fire_time(fire_at=fire, after=after)
        assert result is not None
        # UTC equivalent: 09:30 - 05:00 = 04:30
        assert result.astimezone(UTC).hour == 4
        assert result.astimezone(UTC).minute == 30


# ---------------------------------------------------------------------------
# Cron (recurring) schedules
# ---------------------------------------------------------------------------

class TestCron:
    def test_every_minute(self):
        after = dt(2026, 1, 1, 12, 0, 30)  # 12:00:30 UTC
        result = next_fire_time(cron="* * * * *", after=after)
        assert result is not None
        assert result == dt(2026, 1, 1, 12, 1, 0)

    def test_hourly(self):
        after = dt(2026, 1, 1, 12, 5, 0)
        result = next_fire_time(cron="0 * * * *", after=after)
        assert result == dt(2026, 1, 1, 13, 0, 0)

    def test_daily_midnight(self):
        after = dt(2026, 1, 1, 12, 0, 0)
        result = next_fire_time(cron="0 0 * * *", after=after)
        assert result == dt(2026, 1, 2, 0, 0, 0)

    def test_weekly(self):
        # Every Monday at 09:00 UTC
        # 2026-01-05 is a Monday
        after = dt(2026, 1, 5, 10, 0, 0)  # Monday 10:00 — already passed this week's fire
        result = next_fire_time(cron="0 9 * * 1", after=after)
        assert result is not None
        assert result == dt(2026, 1, 12, 9, 0, 0)  # next Monday

    def test_timezone_awareness(self):
        """Cron fires at correct local time; result is UTC."""
        from zoneinfo import ZoneInfo
        # Berlin UTC+1 in winter. "0 9 * * *" should fire at 08:00 UTC.
        after = dt(2026, 1, 1, 7, 0, 0)  # UTC 07:00 (08:00 Berlin — not yet fired)
        result = next_fire_time(cron="0 9 * * *", tz="Europe/Berlin", after=after)
        assert result is not None
        assert result.astimezone(UTC) == dt(2026, 1, 1, 8, 0, 0)

    def test_timezone_dst_boundary(self):
        """Cron evaluates correctly across a DST boundary (summer: UTC+2)."""
        from zoneinfo import ZoneInfo
        # After clocks spring forward in Berlin (last Sunday of March)
        # 2026-03-29 is the DST change day (UTC+2 from 02:00 local / 01:00 UTC)
        after = dt(2026, 3, 29, 6, 0, 0)  # UTC 06:00 — Berlin already at UTC+2
        result = next_fire_time(cron="0 9 * * *", tz="Europe/Berlin", after=after)
        assert result is not None
        # 09:00 Berlin (UTC+2) = 07:00 UTC
        assert result.astimezone(UTC) == dt(2026, 3, 29, 7, 0, 0)

    def test_result_is_utc(self):
        result = next_fire_time(cron="* * * * *", after=dt(2026, 1, 1, 0, 0, 0))
        assert result is not None
        assert result.tzinfo == UTC

    def test_no_args_raises(self):
        with pytest.raises(ValueError):
            next_fire_time(after=dt(2026, 1, 1))
