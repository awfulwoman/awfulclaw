"""Cron expression parsing and next-fire-time calculation."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter


def next_fire_time(
    *,
    cron: str | None = None,
    fire_at: str | None = None,
    tz: str = "",
    after: datetime | None = None,
) -> datetime | None:
    """Return the next fire time for a schedule.

    For recurring schedules: pass a 5-field ``cron`` expression.
    For one-shot schedules: pass an ISO 8601 ``fire_at`` string.

    ``tz`` is a IANA timezone name (e.g. ``"Europe/Berlin"``). When empty,
    UTC is used. ``after`` defaults to the current time.

    Returns ``None`` if the schedule has already fired and will not recur
    (i.e. a one-shot ``fire_at`` that is in the past).
    """
    if cron is None and fire_at is None:
        raise ValueError("Either cron or fire_at must be provided")

    zone = ZoneInfo(tz) if tz else timezone.utc
    now = after if after is not None else datetime.now(tz=timezone.utc)
    # Ensure *now* is timezone-aware
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if fire_at is not None:
        dt = datetime.fromisoformat(fire_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
        return dt if dt > now else None

    # Recurring cron schedule
    assert cron is not None  # narrowed above by ValueError check
    # croniter works with naive datetimes; we operate in the schedule's timezone
    now_local = now.astimezone(zone)
    # Strip tzinfo for croniter (it operates naively in the given tz)
    now_naive = now_local.replace(tzinfo=None)
    it = croniter(cron, now_naive)
    next_naive: datetime = it.get_next(datetime)
    # Re-attach timezone and convert to UTC for a canonical, comparable result
    next_local = next_naive.replace(tzinfo=zone)
    return next_local.astimezone(timezone.utc)
