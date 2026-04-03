"""Unit tests for agent/mcp/eventkit.py — uses mocked EKEventStore."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import agent.mcp.eventkit as ek


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_calendar(id: str = "cal-1", title: str = "Work", source_title: str = "iCloud") -> MagicMock:
    cal = MagicMock()
    cal.calendarIdentifier.return_value = id
    cal.title.return_value = title
    src = MagicMock()
    src.title.return_value = source_title
    cal.source.return_value = src
    return cal


def _make_event(
    id: str = "evt-1",
    title: str = "Meeting",
    start: str = "2026-04-01T10:00:00",
    end: str = "2026-04-01T11:00:00",
    all_day: bool = False,
    location: str | None = None,
    notes: str | None = None,
    cal: MagicMock | None = None,
) -> MagicMock:
    ev = MagicMock()
    ev.eventIdentifier.return_value = id
    ev.title.return_value = title
    ev.startDate.return_value = start
    ev.endDate.return_value = end
    ev.isAllDay.return_value = all_day
    ev.location.return_value = location
    ev.notes.return_value = notes
    ev.calendar.return_value = cal or _make_calendar()
    return ev


def _make_store(
    calendars: list[Any] | None = None,
    events: list[Any] | None = None,
    save_ok: bool = True,
    remove_ok: bool = True,
) -> MagicMock:
    store = MagicMock()
    store.calendarsForEntityType_.return_value = calendars or []
    store.eventsMatchingPredicate_.return_value = events or []
    store.predicateForEventsWithStartDate_endDate_calendars_.return_value = MagicMock()
    store.saveEvent_span_commit_error_.return_value = (save_ok, None if save_ok else "save error")
    store.removeEvent_span_commit_error_.return_value = (remove_ok, None if remove_ok else "remove error")
    store.defaultCalendarForNewEvents.return_value = _make_calendar()
    return store


def _patch_store(monkeypatch: pytest.MonkeyPatch, store: MagicMock) -> None:
    monkeypatch.setattr(ek, "_get_store", lambda: store)


def _patch_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _parse_date to return the string as-is (no Foundation needed)."""
    monkeypatch.setattr(ek, "_parse_date", lambda s: s)


# ---------------------------------------------------------------------------
# calendar_list
# ---------------------------------------------------------------------------


async def test_calendar_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store(calendars=[])
    _patch_store(monkeypatch, store)

    result = await ek.calendar_list()
    assert result == []


async def test_calendar_list_returns_calendars(monkeypatch: pytest.MonkeyPatch) -> None:
    cal1 = _make_calendar(id="c1", title="Work")
    cal2 = _make_calendar(id="c2", title="Personal")
    store = _make_store(calendars=[cal1, cal2])
    _patch_store(monkeypatch, store)

    result = await ek.calendar_list()
    assert len(result) == 2
    assert result[0] == {"id": "c1", "title": "Work", "source": "iCloud"}
    assert result[1]["title"] == "Personal"


async def test_calendar_list_no_source(monkeypatch: pytest.MonkeyPatch) -> None:
    cal = _make_calendar(id="c1", title="Local")
    cal.source.return_value = None
    store = _make_store(calendars=[cal])
    _patch_store(monkeypatch, store)

    result = await ek.calendar_list()
    assert result[0]["source"] is None


# ---------------------------------------------------------------------------
# calendar_events
# ---------------------------------------------------------------------------


async def test_calendar_events_returns_events(monkeypatch: pytest.MonkeyPatch) -> None:
    ev1 = _make_event(id="e1", title="Standup")
    ev2 = _make_event(id="e2", title="Lunch")
    store = _make_store(events=[ev1, ev2])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_events(start="2026-04-01T00:00:00", end="2026-04-01T23:59:59")
    assert len(result) == 2
    assert result[0]["id"] == "e1"
    assert result[0]["title"] == "Standup"
    assert result[1]["id"] == "e2"


async def test_calendar_events_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store(events=[])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_events(start="2026-04-01T00:00:00", end="2026-04-01T23:59:59")
    assert result == []


async def test_calendar_events_filter_by_calendar_id(monkeypatch: pytest.MonkeyPatch) -> None:
    cal = _make_calendar(id="c1", title="Work")
    ev = _make_event(id="e1", title="Meeting", cal=cal)
    store = _make_store(calendars=[cal], events=[ev])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_events(
        start="2026-04-01T00:00:00", end="2026-04-01T23:59:59", calendar="c1"
    )
    assert len(result) == 1
    assert result[0]["title"] == "Meeting"


async def test_calendar_events_filter_calendar_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    cal = _make_calendar(id="c1", title="Work")
    store = _make_store(calendars=[cal])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_events(
        start="2026-04-01T00:00:00", end="2026-04-01T23:59:59", calendar="nonexistent"
    )
    assert result == []


async def test_calendar_events_filter_by_calendar_title(monkeypatch: pytest.MonkeyPatch) -> None:
    cal = _make_calendar(id="c1", title="Personal")
    ev = _make_event(id="e1", title="Gym", cal=cal)
    store = _make_store(calendars=[cal], events=[ev])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_events(
        start="2026-04-01T00:00:00", end="2026-04-01T23:59:59", calendar="Personal"
    )
    assert result[0]["id"] == "e1"


async def test_calendar_events_includes_location_and_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = _make_event(id="e1", title="Offsite", location="HQ", notes="Bring laptop")
    store = _make_store(events=[ev])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_events(start="2026-04-01T00:00:00", end="2026-04-01T23:59:59")
    assert result[0]["location"] == "HQ"
    assert result[0]["notes"] == "Bring laptop"


# ---------------------------------------------------------------------------
# calendar_create_event
# ---------------------------------------------------------------------------


async def test_calendar_create_event_success(monkeypatch: pytest.MonkeyPatch) -> None:
    new_ev = _make_event(id="new-evt-123", title="New Meeting")
    store = _make_store(save_ok=True)
    # EKEvent.eventWithEventStore_ returns our mock event
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeEvent = 0
    mock_ek.EKSpanThisEvent = 0
    mock_ek.EKEvent.eventWithEventStore_.return_value = new_ev
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_create_event(
        title="New Meeting",
        start="2026-04-01T10:00:00",
        end="2026-04-01T11:00:00",
    )
    assert result == "new-evt-123"
    new_ev.setTitle_.assert_called_once_with("New Meeting")


async def test_calendar_create_event_with_location_and_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    new_ev = _make_event(id="evt-loc", title="Offsite")
    store = _make_store(save_ok=True)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeEvent = 0
    mock_ek.EKSpanThisEvent = 0
    mock_ek.EKEvent.eventWithEventStore_.return_value = new_ev
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    await ek.calendar_create_event(
        title="Offsite",
        start="2026-04-01T09:00:00",
        end="2026-04-01T17:00:00",
        location="HQ",
        notes="Bring badge",
    )
    new_ev.setLocation_.assert_called_once_with("HQ")
    new_ev.setNotes_.assert_called_once_with("Bring badge")


async def test_calendar_create_event_with_calendar_id(monkeypatch: pytest.MonkeyPatch) -> None:
    target_cal = _make_calendar(id="cal-work", title="Work")
    new_ev = _make_event(id="evt-2", title="Review")
    store = _make_store(calendars=[target_cal], save_ok=True)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeEvent = 0
    mock_ek.EKSpanThisEvent = 0
    mock_ek.EKEvent.eventWithEventStore_.return_value = new_ev
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    await ek.calendar_create_event(
        title="Review",
        start="2026-04-01T14:00:00",
        end="2026-04-01T15:00:00",
        calendar_id="cal-work",
    )
    new_ev.setCalendar_.assert_called_once_with(target_cal)


async def test_calendar_create_event_save_error(monkeypatch: pytest.MonkeyPatch) -> None:
    new_ev = _make_event(id="evt-err", title="Bad")
    store = _make_store(save_ok=False)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeEvent = 0
    mock_ek.EKSpanThisEvent = 0
    mock_ek.EKEvent.eventWithEventStore_.return_value = new_ev
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_create_event(
        title="Bad", start="2026-04-01T10:00:00", end="2026-04-01T11:00:00"
    )
    assert result.startswith("Error")


# ---------------------------------------------------------------------------
# calendar_update_event
# ---------------------------------------------------------------------------


async def test_calendar_update_event_title(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = _make_event(id="e1", title="Old Title")
    store = _make_store(save_ok=True)
    store.eventWithIdentifier_.return_value = existing
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKSpanThisEvent = 0
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_update_event(id="e1", title="New Title")
    assert "e1" in result
    existing.setTitle_.assert_called_once_with("New Title")


async def test_calendar_update_event_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store()
    store.eventWithIdentifier_.return_value = None
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKSpanThisEvent = 0
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_update_event(id="ghost", title="Nope")
    assert "Error" in result
    assert "ghost" in result


async def test_calendar_update_event_save_error(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = _make_event(id="e1")
    store = _make_store(save_ok=False)
    store.eventWithIdentifier_.return_value = existing
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKSpanThisEvent = 0
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)

    result = await ek.calendar_update_event(id="e1", title="Updated")
    assert result.startswith("Error")


# ---------------------------------------------------------------------------
# calendar_delete_event
# ---------------------------------------------------------------------------


async def test_calendar_delete_event_success(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = _make_event(id="e1")
    store = _make_store(remove_ok=True)
    store.eventWithIdentifier_.return_value = existing
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKSpanThisEvent = 0
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)

    result = await ek.calendar_delete_event(id="e1")
    assert "e1" in result
    assert "deleted" in result


async def test_calendar_delete_event_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store()
    store.eventWithIdentifier_.return_value = None
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKSpanThisEvent = 0
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)

    result = await ek.calendar_delete_event(id="missing")
    assert "Error" in result
    assert "missing" in result


async def test_calendar_delete_event_remove_error(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = _make_event(id="e1")
    store = _make_store(remove_ok=False)
    store.eventWithIdentifier_.return_value = existing
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKSpanThisEvent = 0
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)

    result = await ek.calendar_delete_event(id="e1")
    assert result.startswith("Error")


# ---------------------------------------------------------------------------
# Reminder mock helpers
# ---------------------------------------------------------------------------


def _make_reminder(
    id: str = "rem-1",
    title: str = "Buy milk",
    completed: bool = False,
    due_components: Any = None,
    notes: str | None = None,
    priority: int = 0,
    cal: MagicMock | None = None,
) -> MagicMock:
    r = MagicMock()
    r.calendarItemIdentifier.return_value = id
    r.title.return_value = title
    r.isCompleted.return_value = completed
    r.dueDateComponents.return_value = due_components
    r.notes.return_value = notes
    r.priority.return_value = priority
    r.calendar.return_value = cal or _make_calendar(id="list-1", title="Reminders")
    return r


def _make_reminder_store(
    lists: list[Any] | None = None,
    reminders: list[Any] | None = None,
    save_ok: bool = True,
    remove_ok: bool = True,
) -> MagicMock:
    store = MagicMock()
    store.calendarsForEntityType_.return_value = lists or []
    store.remindersMatchingPredicate_.return_value = reminders or []
    store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_.return_value = MagicMock()
    store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_.return_value = MagicMock()
    store.saveReminder_commit_error_.return_value = (save_ok, None if save_ok else "save error")
    store.removeReminder_commit_error_.return_value = (remove_ok, None if remove_ok else "remove error")
    store.defaultCalendarForNewReminders.return_value = _make_calendar()
    return store


def _patch_datecomponents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _str_to_datecomponents to return the string as-is."""
    monkeypatch.setattr(ek, "_str_to_datecomponents", lambda s: s)


# ---------------------------------------------------------------------------
# reminders_lists
# ---------------------------------------------------------------------------


async def test_reminders_lists_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_reminder_store(lists=[])
    _patch_store(monkeypatch, store)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)

    result = await ek.reminders_lists()
    assert result == []


async def test_reminders_lists_returns_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    list1 = _make_calendar(id="l1", title="Reminders")
    list2 = _make_calendar(id="l2", title="Work")
    store = _make_reminder_store(lists=[list1, list2])
    _patch_store(monkeypatch, store)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)

    result = await ek.reminders_lists()
    assert len(result) == 2
    assert result[0]["id"] == "l1"
    assert result[1]["title"] == "Work"


# ---------------------------------------------------------------------------
# reminders_incomplete
# ---------------------------------------------------------------------------


async def test_reminders_incomplete_returns_reminders(monkeypatch: pytest.MonkeyPatch) -> None:
    r1 = _make_reminder(id="r1", title="Buy milk")
    r2 = _make_reminder(id="r2", title="Call dentist")
    store = _make_reminder_store(reminders=[r1, r2])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)

    result = await ek.reminders_incomplete()
    assert len(result) == 2
    assert result[0]["id"] == "r1"
    assert result[0]["title"] == "Buy milk"
    assert result[0]["completed"] is False


async def test_reminders_incomplete_filter_by_list(monkeypatch: pytest.MonkeyPatch) -> None:
    lst = _make_calendar(id="l1", title="Work")
    r1 = _make_reminder(id="r1", title="Send report", cal=lst)
    store = _make_reminder_store(lists=[lst], reminders=[r1])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)

    result = await ek.reminders_incomplete(list="Work")
    assert len(result) == 1
    assert result[0]["id"] == "r1"


async def test_reminders_incomplete_unknown_list_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    lst = _make_calendar(id="l1", title="Work")
    store = _make_reminder_store(lists=[lst])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)

    result = await ek.reminders_incomplete(list="nonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# reminders_completed
# ---------------------------------------------------------------------------


async def test_reminders_completed_returns_reminders(monkeypatch: pytest.MonkeyPatch) -> None:
    r1 = _make_reminder(id="r1", title="Done task", completed=True)
    store = _make_reminder_store(reminders=[r1])
    _patch_store(monkeypatch, store)
    _patch_date(monkeypatch)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)

    result = await ek.reminders_completed()
    assert len(result) == 1
    assert result[0]["completed"] is True


# ---------------------------------------------------------------------------
# reminder_create
# ---------------------------------------------------------------------------


async def test_reminder_create_success(monkeypatch: pytest.MonkeyPatch) -> None:
    new_r = _make_reminder(id="new-rem-1", title="Groceries")
    store = _make_reminder_store(save_ok=True)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    mock_ek.EKReminder.reminderWithEventStore_.return_value = new_r
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_datecomponents(monkeypatch)

    result = await ek.reminder_create(title="Groceries")
    assert result == "new-rem-1"
    new_r.setTitle_.assert_called_once_with("Groceries")


async def test_reminder_create_with_due_and_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    new_r = _make_reminder(id="rem-due", title="Report")
    store = _make_reminder_store(save_ok=True)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    mock_ek.EKReminder.reminderWithEventStore_.return_value = new_r
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_datecomponents(monkeypatch)

    await ek.reminder_create(title="Report", due="2026-04-05T09:00:00", notes="Quarterly")
    new_r.setDueDateComponents_.assert_called_once_with("2026-04-05T09:00:00")
    new_r.setNotes_.assert_called_once_with("Quarterly")


async def test_reminder_create_save_error(monkeypatch: pytest.MonkeyPatch) -> None:
    new_r = _make_reminder(id="rem-err", title="Bad")
    store = _make_reminder_store(save_ok=False)
    import agent.mcp.eventkit as eventkit_mod
    mock_ek = MagicMock()
    mock_ek.EKEntityTypeReminder = 1
    mock_ek.EKReminder.reminderWithEventStore_.return_value = new_r
    monkeypatch.setattr(eventkit_mod, "_EK", mock_ek)
    _patch_store(monkeypatch, store)
    _patch_datecomponents(monkeypatch)

    result = await ek.reminder_create(title="Bad")
    assert result.startswith("Error")


# ---------------------------------------------------------------------------
# reminder_complete
# ---------------------------------------------------------------------------


async def test_reminder_complete_success(monkeypatch: pytest.MonkeyPatch) -> None:
    r = _make_reminder(id="r1", completed=False)
    store = _make_reminder_store(save_ok=True)
    store.calendarItemWithIdentifier_.return_value = r
    _patch_store(monkeypatch, store)

    result = await ek.reminder_complete(id="r1")
    assert "r1" in result
    assert "complete" in result
    r.setCompleted_.assert_called_once_with(True)


async def test_reminder_complete_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_reminder_store()
    store.calendarItemWithIdentifier_.return_value = None
    _patch_store(monkeypatch, store)

    result = await ek.reminder_complete(id="ghost")
    assert "Error" in result
    assert "ghost" in result


# ---------------------------------------------------------------------------
# reminder_update
# ---------------------------------------------------------------------------


async def test_reminder_update_title(monkeypatch: pytest.MonkeyPatch) -> None:
    r = _make_reminder(id="r1", title="Old")
    store = _make_reminder_store(save_ok=True)
    store.calendarItemWithIdentifier_.return_value = r
    _patch_store(monkeypatch, store)
    _patch_datecomponents(monkeypatch)

    result = await ek.reminder_update(id="r1", title="New")
    assert "r1" in result
    r.setTitle_.assert_called_once_with("New")


async def test_reminder_update_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_reminder_store()
    store.calendarItemWithIdentifier_.return_value = None
    _patch_store(monkeypatch, store)
    _patch_datecomponents(monkeypatch)

    result = await ek.reminder_update(id="ghost", title="Nope")
    assert "Error" in result
    assert "ghost" in result


# ---------------------------------------------------------------------------
# reminder_delete
# ---------------------------------------------------------------------------


async def test_reminder_delete_success(monkeypatch: pytest.MonkeyPatch) -> None:
    r = _make_reminder(id="r1")
    store = _make_reminder_store(remove_ok=True)
    store.calendarItemWithIdentifier_.return_value = r
    _patch_store(monkeypatch, store)

    result = await ek.reminder_delete(id="r1")
    assert "r1" in result
    assert "deleted" in result


async def test_reminder_delete_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_reminder_store()
    store.calendarItemWithIdentifier_.return_value = None
    _patch_store(monkeypatch, store)

    result = await ek.reminder_delete(id="missing")
    assert "Error" in result
    assert "missing" in result


async def test_reminder_delete_remove_error(monkeypatch: pytest.MonkeyPatch) -> None:
    r = _make_reminder(id="r1")
    store = _make_reminder_store(remove_ok=False)
    store.calendarItemWithIdentifier_.return_value = r
    _patch_store(monkeypatch, store)

    result = await ek.reminder_delete(id="r1")
    assert result.startswith("Error")
