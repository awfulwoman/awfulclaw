"""Tests for MCP gcal server."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_token_path_is_outside_memory() -> None:
    from awfulclaw_mcp.gcal import _token_path

    path = _token_path()
    assert path.name == "gcal_token.json"
    assert ".config" in str(path)
    assert "awfulclaw" in str(path)
    assert "memory" not in str(path)


def _make_service(events: list[dict]) -> MagicMock:  # type: ignore[type-arg]
    """Build a mock Google Calendar service that returns *events* from list()."""
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": events}
    return service


def test_gcal_list_no_events() -> None:
    from awfulclaw_mcp.gcal import gcal_list

    with patch("awfulclaw_mcp.gcal._get_service", return_value=_make_service([])):
        result = gcal_list(start="2026-04-01T00:00:00Z", end="2026-04-02T00:00:00Z")
    assert "No events" in result


def test_gcal_list_returns_events() -> None:
    from awfulclaw_mcp.gcal import gcal_list

    events = [
        {
            "id": "abc123",
            "summary": "Team standup",
            "start": {"dateTime": "2026-04-01T09:00:00Z"},
            "end": {"dateTime": "2026-04-01T09:30:00Z"},
        }
    ]
    with patch("awfulclaw_mcp.gcal._get_service", return_value=_make_service(events)):
        result = gcal_list(start="2026-04-01T00:00:00Z", end="2026-04-02T00:00:00Z")
    assert "abc123" in result
    assert "Team standup" in result
    assert "2026-04-01T09:00:00Z" in result


def test_gcal_list_handles_error() -> None:
    from awfulclaw_mcp.gcal import gcal_list

    error_msg = "Not authenticated — run: uv run python -m awfulclaw_mcp.gcal --auth"
    with patch("awfulclaw_mcp.gcal._get_service", side_effect=RuntimeError(error_msg)):
        result = gcal_list(start="2026-04-01T00:00:00Z", end="2026-04-02T00:00:00Z")
    assert "[gcal error:" in result
    assert "Not authenticated" in result


def test_gcal_create_returns_event_id() -> None:
    from awfulclaw_mcp.gcal import gcal_create

    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {"id": "evt001"}

    with patch("awfulclaw_mcp.gcal._get_service", return_value=service):
        result = gcal_create(
            title="Dentist",
            start="2026-04-01T10:00:00Z",
            end="2026-04-01T11:00:00Z",
        )
    assert "evt001" in result
    assert "Created" in result


def test_gcal_create_passes_description() -> None:
    from awfulclaw_mcp.gcal import gcal_create

    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {"id": "evt002"}

    with patch("awfulclaw_mcp.gcal._get_service", return_value=service):
        gcal_create(
            title="Meeting",
            start="2026-04-01T14:00:00Z",
            end="2026-04-01T15:00:00Z",
            description="Quarterly review",
        )

    call_kwargs = service.events.return_value.insert.call_args.kwargs
    assert call_kwargs["body"]["description"] == "Quarterly review"


def test_gcal_create_handles_error() -> None:
    from awfulclaw_mcp.gcal import gcal_create

    with patch("awfulclaw_mcp.gcal._get_service", side_effect=RuntimeError("API down")):
        result = gcal_create(title="X", start="2026-04-01T10:00:00Z", end="2026-04-01T11:00:00Z")
    assert "[gcal error:" in result
    assert "API down" in result


def _make_update_service(existing_event: dict) -> MagicMock:  # type: ignore[type-arg]
    """Build a mock service for update — get() returns existing_event."""
    service = MagicMock()
    service.events.return_value.get.return_value.execute.return_value = dict(existing_event)
    service.events.return_value.update.return_value.execute.return_value = existing_event
    return service


def test_gcal_update_title() -> None:
    from awfulclaw_mcp.gcal import gcal_update

    existing = {
        "id": "evt003",
        "summary": "Old title",
        "start": {"dateTime": "2026-04-01T10:00:00Z"},
        "end": {"dateTime": "2026-04-01T11:00:00Z"},
    }
    service = _make_update_service(existing)

    with patch("awfulclaw_mcp.gcal._get_service", return_value=service):
        result = gcal_update(event_id="evt003", title="New title")

    assert "Updated" in result
    assert "evt003" in result
    call_kwargs = service.events.return_value.update.call_args.kwargs
    assert call_kwargs["body"]["summary"] == "New title"


def test_gcal_update_skips_empty_fields() -> None:
    from awfulclaw_mcp.gcal import gcal_update

    existing = {
        "id": "evt004",
        "summary": "Keep me",
        "start": {"dateTime": "2026-04-01T10:00:00Z"},
        "end": {"dateTime": "2026-04-01T11:00:00Z"},
    }
    service = _make_update_service(existing)

    with patch("awfulclaw_mcp.gcal._get_service", return_value=service):
        gcal_update(event_id="evt004", title="")  # empty title — should not overwrite

    call_kwargs = service.events.return_value.update.call_args.kwargs
    assert call_kwargs["body"]["summary"] == "Keep me"


def test_gcal_update_handles_error() -> None:
    from awfulclaw_mcp.gcal import gcal_update

    with patch("awfulclaw_mcp.gcal._get_service", side_effect=RuntimeError("not found")):
        result = gcal_update(event_id="bad_id", title="X")
    assert "[gcal error:" in result
    assert "not found" in result


def test_gcal_delete_success() -> None:
    from awfulclaw_mcp.gcal import gcal_delete

    service = MagicMock()
    service.events.return_value.delete.return_value.execute.return_value = None

    with patch("awfulclaw_mcp.gcal._get_service", return_value=service):
        result = gcal_delete(event_id="evt005")

    assert "Deleted" in result
    assert "evt005" in result
    service.events.return_value.delete.assert_called_once_with(
        calendarId="primary", eventId="evt005"
    )


def test_gcal_delete_custom_calendar() -> None:
    from awfulclaw_mcp.gcal import gcal_delete

    service = MagicMock()
    service.events.return_value.delete.return_value.execute.return_value = None

    with patch("awfulclaw_mcp.gcal._get_service", return_value=service):
        gcal_delete(event_id="evt006", calendar_id="work@example.com")

    service.events.return_value.delete.assert_called_once_with(
        calendarId="work@example.com", eventId="evt006"
    )


def test_gcal_delete_handles_error() -> None:
    from awfulclaw_mcp.gcal import gcal_delete

    with patch("awfulclaw_mcp.gcal._get_service", side_effect=RuntimeError("event not found")):
        result = gcal_delete(event_id="bad_id")
    assert "[gcal error:" in result
    assert "event not found" in result
