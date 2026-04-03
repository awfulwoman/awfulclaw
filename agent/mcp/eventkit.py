"""eventkit MCP server — calendar and reminder read/write tools via macOS EventKit.

Exposes:
  calendar_list()                                 — list all calendars
  calendar_events(start, end, calendar?)          — events in a date range
  calendar_create_event(title, start, end, ...)   — create a calendar event
  calendar_update_event(id, ...)                  — update an event
  calendar_delete_event(id)                       — delete an event

  reminders_lists()                               — list all reminder lists
  reminders_incomplete(list?, due_before?)        — incomplete reminders
  reminders_completed(list?, completed_after?)    — completed reminders
  reminder_create(title, ...)                     — create a reminder
  reminder_complete(id)                           — mark reminder complete
  reminder_update(id, ...)                        — update a reminder
  reminder_delete(id)                             — delete a reminder

Requires macOS with pyobjc-framework-EventKit installed.
"""
from __future__ import annotations

import asyncio
import datetime
import threading
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
# Shared store — created once, access requested at startup
# ---------------------------------------------------------------------------

_store: Any = None
_store_lock = threading.Lock()


def _init_store() -> Any:
    """Create EKEventStore and request access for both calendars and reminders."""
    if not _HAS_EVENTKIT:
        raise RuntimeError("pyobjc-framework-EventKit not installed — requires macOS")

    store = _EK.EKEventStore.alloc().init()  # type: ignore[union-attr]

    for entity_type in (_EK.EKEntityTypeEvent, _EK.EKEntityTypeReminder):  # type: ignore[union-attr]
        done = threading.Event()
        store.requestAccessToEntityType_completion_(entity_type, lambda granted, err: done.set())
        done.wait(timeout=10)

    return store


def _get_store() -> Any:
    global _store
    with _store_lock:
        if _store is None:
            _store = _init_store()
    return _store


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


# ---------------------------------------------------------------------------
# Reminder helpers
# ---------------------------------------------------------------------------

_NSUndefinedDateComponent = 2147483647  # NSUndefinedDateComponent (INT_MAX on 32-bit)
_NSUndefinedDateComponent64 = 9223372036854775807  # INT64_MAX on 64-bit


def _datecomponents_to_str(dc: Any) -> Optional[str]:
    """Convert NSDateComponents to an ISO date/datetime string, or None."""
    if dc is None:
        return None
    try:
        year = int(dc.year())
        month = int(dc.month())
        day = int(dc.day())
        if year in (_NSUndefinedDateComponent, _NSUndefinedDateComponent64):
            return None
        hour = int(dc.hour())
        minute = int(dc.minute())
        if hour in (_NSUndefinedDateComponent, _NSUndefinedDateComponent64):
            return f"{year:04d}-{month:02d}-{day:02d}"
        return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00"
    except Exception:
        return None


def _str_to_datecomponents(s: str) -> Any:
    """Convert an ISO date string to NSDateComponents."""
    from Foundation import NSDateComponents  # type: ignore[import-not-found]

    dt = datetime.datetime.fromisoformat(s)
    dc = NSDateComponents.alloc().init()
    dc.setYear_(dt.year)
    dc.setMonth_(dt.month)
    dc.setDay_(dt.day)
    dc.setHour_(dt.hour)
    dc.setMinute_(dt.minute)
    dc.setSecond_(dt.second)
    return dc


def _reminder_to_dict(r: Any) -> dict:
    cal = r.calendar()
    return {
        "id": str(r.calendarItemIdentifier()),
        "title": str(r.title()),
        "completed": bool(r.isCompleted()),
        "due": _datecomponents_to_str(r.dueDateComponents()),
        "notes": str(r.notes()) if r.notes() else None,
        "priority": int(r.priority()),
        "list": str(cal.title()) if cal else None,
        "list_id": str(cal.calendarIdentifier()) if cal else None,
    }


def _get_reminder_calendars(store: Any, list_name: Optional[str]) -> Optional[list]:
    all_lists = store.calendarsForEntityType_(_EK.EKEntityTypeReminder)  # type: ignore[union-attr]
    if list_name is None:
        return None  # None means all lists
    selected = [
        c
        for c in all_lists
        if str(c.calendarIdentifier()) == list_name or str(c.title()) == list_name
    ]
    return selected or []


# ---------------------------------------------------------------------------
# Reminder sync implementations
# ---------------------------------------------------------------------------


def _sync_reminders_lists() -> list[dict]:
    store = _get_store()
    lists = store.calendarsForEntityType_(_EK.EKEntityTypeReminder)  # type: ignore[union-attr]
    return [_calendar_to_dict(c) for c in lists]


def _sync_reminders_incomplete(list_name: Optional[str], due_before: Optional[str]) -> list[dict]:
    store = _get_store()
    calendars = _get_reminder_calendars(store, list_name)
    if isinstance(calendars, list) and len(calendars) == 0:
        return []
    end_date = _parse_date(due_before) if due_before else None
    pred = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None, end_date, calendars
    )
    reminders = store.remindersMatchingPredicate_(pred)
    return [_reminder_to_dict(r) for r in (reminders or [])]


def _sync_reminders_completed(list_name: Optional[str], completed_after: Optional[str]) -> list[dict]:
    store = _get_store()
    calendars = _get_reminder_calendars(store, list_name)
    if isinstance(calendars, list) and len(calendars) == 0:
        return []
    start_date = _parse_date(completed_after) if completed_after else None
    pred = store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(
        start_date, None, calendars
    )
    reminders = store.remindersMatchingPredicate_(pred)
    return [_reminder_to_dict(r) for r in (reminders or [])]


def _sync_reminder_create(
    title: str,
    list_id: Optional[str],
    due: Optional[str],
    notes: Optional[str],
    priority: int,
) -> str:
    store = _get_store()
    reminder = _EK.EKReminder.reminderWithEventStore_(store)  # type: ignore[union-attr]
    reminder.setTitle_(title)
    if notes:
        reminder.setNotes_(notes)
    if priority != 0:
        reminder.setPriority_(priority)
    if due:
        reminder.setDueDateComponents_(_str_to_datecomponents(due))

    if list_id:
        all_lists = store.calendarsForEntityType_(_EK.EKEntityTypeReminder)  # type: ignore[union-attr]
        cal = next(
            (c for c in all_lists if str(c.calendarIdentifier()) == list_id), None
        )
        if cal:
            reminder.setCalendar_(cal)
    else:
        reminder.setCalendar_(store.defaultCalendarForNewReminders())

    ok, err = store.saveReminder_commit_error_(reminder, True, None)
    if not ok:
        return f"Error saving reminder: {err}"
    return str(reminder.calendarItemIdentifier())


def _sync_reminder_complete(reminder_id: str) -> str:
    store = _get_store()
    reminders_list = store.calendarItemWithIdentifier_(reminder_id)
    if reminders_list is None:
        return f"Error: reminder {reminder_id!r} not found"
    reminders_list.setCompleted_(True)
    ok, err = store.saveReminder_commit_error_(reminders_list, True, None)
    if not ok:
        return f"Error completing reminder: {err}"
    return f"Reminder {reminder_id!r} marked complete"


def _sync_reminder_update(
    reminder_id: str,
    title: Optional[str],
    due: Optional[str],
    notes: Optional[str],
    priority: Optional[int],
) -> str:
    store = _get_store()
    reminder = store.calendarItemWithIdentifier_(reminder_id)
    if reminder is None:
        return f"Error: reminder {reminder_id!r} not found"
    if title is not None:
        reminder.setTitle_(title)
    if notes is not None:
        reminder.setNotes_(notes)
    if priority is not None:
        reminder.setPriority_(priority)
    if due is not None:
        reminder.setDueDateComponents_(_str_to_datecomponents(due))
    ok, err = store.saveReminder_commit_error_(reminder, True, None)
    if not ok:
        return f"Error updating reminder: {err}"
    return f"Reminder {reminder_id!r} updated"


def _sync_reminder_delete(reminder_id: str) -> str:
    store = _get_store()
    reminder = store.calendarItemWithIdentifier_(reminder_id)
    if reminder is None:
        return f"Error: reminder {reminder_id!r} not found"
    ok, err = store.removeReminder_commit_error_(reminder, True, None)
    if not ok:
        return f"Error deleting reminder: {err}"
    return f"Reminder {reminder_id!r} deleted"


# ---------------------------------------------------------------------------
# Reminder MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
async def reminders_lists() -> list[dict]:
    """Return all reminder lists available in macOS Reminders."""
    return await asyncio.to_thread(_sync_reminders_lists)


@mcp.tool()
async def reminders_incomplete(
    list: Optional[str] = None,
    due_before: Optional[str] = None,
) -> list[dict]:
    """Return incomplete reminders.

    list: optional reminder list id or title to filter by
    due_before: optional ISO 8601 string — only reminders due before this date
    """
    return await asyncio.to_thread(_sync_reminders_incomplete, list, due_before)


@mcp.tool()
async def reminders_completed(
    list: Optional[str] = None,
    completed_after: Optional[str] = None,
) -> list[dict]:
    """Return completed reminders.

    list: optional reminder list id or title to filter by
    completed_after: optional ISO 8601 string — only reminders completed after this date
    """
    return await asyncio.to_thread(_sync_reminders_completed, list, completed_after)


@mcp.tool()
async def reminder_create(
    title: str,
    list_id: Optional[str] = None,
    due: Optional[str] = None,
    notes: Optional[str] = None,
    priority: int = 0,
) -> str:
    """Create a reminder. Returns the new reminder's id on success.

    priority: 0=none, 1=high, 5=medium, 9=low
    due: optional ISO 8601 date/datetime string
    """
    return await asyncio.to_thread(_sync_reminder_create, title, list_id, due, notes, priority)


@mcp.tool()
async def reminder_complete(id: str) -> str:
    """Mark a reminder as complete by id."""
    return await asyncio.to_thread(_sync_reminder_complete, id)


@mcp.tool()
async def reminder_update(
    id: str,
    title: Optional[str] = None,
    due: Optional[str] = None,
    notes: Optional[str] = None,
    priority: Optional[int] = None,
) -> str:
    """Update fields on an existing reminder."""
    return await asyncio.to_thread(_sync_reminder_update, id, title, due, notes, priority)


@mcp.tool()
async def reminder_delete(id: str) -> str:
    """Delete a reminder by id."""
    return await asyncio.to_thread(_sync_reminder_delete, id)


if __name__ == "__main__":
    mcp.run()
