"""eventkit MCP server — calendar read/write tools via macOS EventKit.

Exposes:
  calendar_list()                                 — list all calendars
  calendar_events(start, end, calendar?)          — events in a date range
  calendar_create_event(title, start, end, ...)   — create a calendar event
  calendar_update_event(id, ...)                  — update an event
  calendar_delete_event(id)                       — delete an event

Requires macOS with pyobjc-framework-EventKit installed.
"""
from __future__ import annotations

import asyncio
import datetime
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("eventkit")

try:
    import EventKit as _EK  # type: ignore[import-not-found]

    _HAS_EVENTKIT = True
except ImportError:
    _EK = None  # type: ignore[assignment]
    _HAS_EVENTKIT = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_store() -> Any:
    if not _HAS_EVENTKIT:
        raise RuntimeError("pyobjc-framework-EventKit not installed — requires macOS")
    return _EK.EKEventStore.alloc().init()  # type: ignore[union-attr]


def _parse_date(s: str) -> Any:
    """Convert an ISO 8601 string to NSDate."""
    from Foundation import NSDate  # type: ignore[import-not-found]

    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return NSDate.alloc().initWithTimeIntervalSince1970_(dt.timestamp())


def _calendar_to_dict(cal: Any) -> dict:
    return {
        "id": str(cal.calendarIdentifier()),
        "title": str(cal.title()),
        "source": str(cal.source().title()) if cal.source() else None,
    }


def _event_to_dict(ev: Any) -> dict:
    cal = ev.calendar()
    return {
        "id": str(ev.eventIdentifier()),
        "title": str(ev.title()),
        "start": str(ev.startDate()),
        "end": str(ev.endDate()),
        "all_day": bool(ev.isAllDay()),
        "location": str(ev.location()) if ev.location() else None,
        "notes": str(ev.notes()) if ev.notes() else None,
        "calendar": str(cal.title()) if cal else None,
        "calendar_id": str(cal.calendarIdentifier()) if cal else None,
    }


# ---------------------------------------------------------------------------
# Sync implementations (run in a thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _sync_calendar_list() -> list[dict]:
    store = _get_store()
    cals = store.calendarsForEntityType_(_EK.EKEntityTypeEvent)  # type: ignore[union-attr]
    return [_calendar_to_dict(c) for c in cals]


def _sync_calendar_events(start: str, end: str, calendar: Optional[str]) -> list[dict]:
    store = _get_store()
    start_date = _parse_date(start)
    end_date = _parse_date(end)

    selected: Optional[list] = None
    if calendar:
        all_cals = store.calendarsForEntityType_(_EK.EKEntityTypeEvent)  # type: ignore[union-attr]
        selected = [
            c
            for c in all_cals
            if str(c.calendarIdentifier()) == calendar or str(c.title()) == calendar
        ]
        if not selected:
            return []

    pred = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_date, end_date, selected
    )
    events = store.eventsMatchingPredicate_(pred)
    return [_event_to_dict(e) for e in (events or [])]


def _sync_create_event(
    title: str,
    start: str,
    end: str,
    calendar_id: Optional[str],
    all_day: bool,
    location: Optional[str],
    notes: Optional[str],
) -> str:
    store = _get_store()
    ev = _EK.EKEvent.eventWithEventStore_(store)  # type: ignore[union-attr]
    ev.setTitle_(title)
    ev.setStartDate_(_parse_date(start))
    ev.setEndDate_(_parse_date(end))
    ev.setAllDay_(all_day)
    if location:
        ev.setLocation_(location)
    if notes:
        ev.setNotes_(notes)

    if calendar_id:
        all_cals = store.calendarsForEntityType_(_EK.EKEntityTypeEvent)  # type: ignore[union-attr]
        cal = next(
            (c for c in all_cals if str(c.calendarIdentifier()) == calendar_id), None
        )
        if cal:
            ev.setCalendar_(cal)
    else:
        ev.setCalendar_(store.defaultCalendarForNewEvents())

    ok, err = store.saveEvent_span_commit_error_(ev, _EK.EKSpanThisEvent, True, None)  # type: ignore[union-attr]
    if not ok:
        return f"Error saving event: {err}"
    return str(ev.eventIdentifier())


def _sync_update_event(
    event_id: str,
    title: Optional[str],
    start: Optional[str],
    end: Optional[str],
    all_day: Optional[bool],
    location: Optional[str],
    notes: Optional[str],
) -> str:
    store = _get_store()
    ev = store.eventWithIdentifier_(event_id)
    if ev is None:
        return f"Error: event {event_id!r} not found"

    if title is not None:
        ev.setTitle_(title)
    if start is not None:
        ev.setStartDate_(_parse_date(start))
    if end is not None:
        ev.setEndDate_(_parse_date(end))
    if all_day is not None:
        ev.setAllDay_(all_day)
    if location is not None:
        ev.setLocation_(location)
    if notes is not None:
        ev.setNotes_(notes)

    ok, err = store.saveEvent_span_commit_error_(ev, _EK.EKSpanThisEvent, True, None)  # type: ignore[union-attr]
    if not ok:
        return f"Error updating event: {err}"
    return f"Event {event_id!r} updated"


def _sync_delete_event(event_id: str) -> str:
    store = _get_store()
    ev = store.eventWithIdentifier_(event_id)
    if ev is None:
        return f"Error: event {event_id!r} not found"
    ok, err = store.removeEvent_span_commit_error_(ev, _EK.EKSpanThisEvent, True, None)  # type: ignore[union-attr]
    if not ok:
        return f"Error deleting event: {err}"
    return f"Event {event_id!r} deleted"


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
async def calendar_list() -> list[dict]:
    """Return all calendars available in macOS Calendar."""
    return await asyncio.to_thread(_sync_calendar_list)


@mcp.tool()
async def calendar_events(
    start: str,
    end: str,
    calendar: Optional[str] = None,
) -> list[dict]:
    """Return events in the date range [start, end].

    start/end: ISO 8601 strings (e.g. '2026-04-01T00:00:00')
    calendar: optional calendar id or title to filter by
    """
    return await asyncio.to_thread(_sync_calendar_events, start, end, calendar)


@mcp.tool()
async def calendar_create_event(
    title: str,
    start: str,
    end: str,
    calendar_id: Optional[str] = None,
    all_day: bool = False,
    location: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Create a calendar event. Returns the new event's id on success."""
    return await asyncio.to_thread(
        _sync_create_event, title, start, end, calendar_id, all_day, location, notes
    )


@mcp.tool()
async def calendar_update_event(
    id: str,
    title: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    all_day: Optional[bool] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Update fields on an existing calendar event."""
    return await asyncio.to_thread(
        _sync_update_event, id, title, start, end, all_day, location, notes
    )


@mcp.tool()
async def calendar_delete_event(id: str) -> str:
    """Delete a calendar event by id."""
    return await asyncio.to_thread(_sync_delete_event, id)


if __name__ == "__main__":
    mcp.run()
