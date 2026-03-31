# Google Calendar MCP Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `gcal` MCP server to awfulclaw that gives the agent full CRUD access to Google Calendar via four tools.

**Architecture:** A new `app/awfulclaw_mcp/gcal.py` module following the exact pattern of `imap.py` — a FastMCP server with tool functions that delegate to helpers, errors returned as `[gcal error: ...]` strings. Auth tokens live in `~/.config/awfulclaw/gcal_token.json` (outside `memory/`). A `--auth` CLI flag triggers the one-time OAuth flow.

**Tech Stack:** `google-api-python-client`, `google-auth-oauthlib`, `mcp.server.fastmcp.FastMCP`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modify | Add Google API deps |
| `app/awfulclaw_mcp/gcal.py` | Create | MCP server — auth helpers + 4 tools |
| `app/tests/test_mcp_gcal.py` | Create | Tests for all 4 tools |
| `config/mcp_servers.json` | Modify | Register the gcal server |
| `CLAUDE.md` | Modify | Document setup steps |

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add google deps to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list:

```toml
[project]
dependencies = [
    "croniter",
    "ddgs>=9.12.0",
    "google-api-python-client",
    "google-auth-oauthlib",
    "httpx",
    "mcp>=1.26.0",
    "python-dotenv",
]
```

- [ ] **Step 2: Sync dependencies**

```bash
uv sync --extra dev
```

Expected: resolves and installs `google-api-python-client` and `google-auth-oauthlib` with no errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add google-api-python-client and google-auth-oauthlib deps"
```

---

### Task 2: Auth Helpers

**Files:**
- Create: `app/awfulclaw_mcp/gcal.py`
- Create: `app/tests/test_mcp_gcal.py`

- [ ] **Step 1: Write the failing test for `_token_path`**

Create `app/tests/test_mcp_gcal.py`:

```python
"""Tests for MCP gcal server."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_token_path_is_outside_memory() -> None:
    from awfulclaw_mcp.gcal import _token_path

    path = _token_path()
    assert path.name == "gcal_token.json"
    assert ".config" in str(path)
    assert "awfulclaw" in str(path)
    assert "memory" not in str(path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_token_path_is_outside_memory -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` (module doesn't exist yet).

- [ ] **Step 3: Create `app/awfulclaw_mcp/gcal.py` with auth helpers**

```python
"""MCP server for Google Calendar CRUD operations."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("gcal")

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _token_path() -> Path:
    return Path.home() / ".config" / "awfulclaw" / "gcal_token.json"


def _get_service() -> object:
    """Load credentials and return a Google Calendar API service object.

    Refreshes an expired token automatically. Raises RuntimeError if no token
    exists (i.e. --auth has not been run).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = _token_path()
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Not authenticated — run: uv run python -m awfulclaw_mcp.gcal --auth"
            )

    return build("calendar", "v3", credentials=creds)


def _run_auth() -> None:
    """Run the OAuth consent flow and save the resulting token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret_path = os.getenv("GOOGLE_CLIENT_SECRET_PATH")
    if not secret_path:
        print("Error: GOOGLE_CLIENT_SECRET_PATH is not set in .env", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = _token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Credentials saved to {token_path}")


if __name__ == "__main__":
    if "--auth" in sys.argv:
        _run_auth()
    else:
        mcp.run()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_token_path_is_outside_memory -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/awfulclaw_mcp/gcal.py app/tests/test_mcp_gcal.py
git commit -m "feat: add gcal MCP server skeleton with auth helpers"
```

---

### Task 3: `gcal_list` Tool

**Files:**
- Modify: `app/awfulclaw_mcp/gcal.py`
- Modify: `app/tests/test_mcp_gcal.py`

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_mcp_gcal.py`:

```python
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

    with patch("awfulclaw_mcp.gcal._get_service", side_effect=RuntimeError("Not authenticated — run: uv run python -m awfulclaw_mcp.gcal --auth")):
        result = gcal_list(start="2026-04-01T00:00:00Z", end="2026-04-02T00:00:00Z")
    assert "[gcal error:" in result
    assert "Not authenticated" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_gcal_list_no_events app/tests/test_mcp_gcal.py::test_gcal_list_returns_events app/tests/test_mcp_gcal.py::test_gcal_list_handles_error -v
```

Expected: FAIL — `gcal_list` is not defined.

- [ ] **Step 3: Implement `gcal_list`**

Add before `if __name__ == "__main__":` in `app/awfulclaw_mcp/gcal.py`:

```python
@mcp.tool()
def gcal_list(start: str, end: str, calendar_id: str = "primary") -> str:
    """List Google Calendar events between two ISO 8601 datetimes.

    Args:
        start: ISO 8601 start datetime (e.g. "2026-04-01T00:00:00Z")
        end: ISO 8601 end datetime (e.g. "2026-04-02T00:00:00Z")
        calendar_id: Calendar to query (default: "primary")
    """
    try:
        service = _get_service()
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
        if not events:
            return "[No events]"
        lines: list[str] = []
        for e in events:
            start_dt = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
            end_dt = e.get("end", {}).get("dateTime", e.get("end", {}).get("date", ""))
            lines.append(f"id={e['id']} | {e.get('summary', '(no title)')} | {start_dt} → {end_dt}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[gcal error: {exc}]"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_gcal_list_no_events app/tests/test_mcp_gcal.py::test_gcal_list_returns_events app/tests/test_mcp_gcal.py::test_gcal_list_handles_error -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/awfulclaw_mcp/gcal.py app/tests/test_mcp_gcal.py
git commit -m "feat: add gcal_list MCP tool"
```

---

### Task 4: `gcal_create` Tool

**Files:**
- Modify: `app/awfulclaw_mcp/gcal.py`
- Modify: `app/tests/test_mcp_gcal.py`

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_mcp_gcal.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_gcal_create_returns_event_id app/tests/test_mcp_gcal.py::test_gcal_create_passes_description app/tests/test_mcp_gcal.py::test_gcal_create_handles_error -v
```

Expected: FAIL — `gcal_create` is not defined.

- [ ] **Step 3: Implement `gcal_create`**

Add after `gcal_list` in `app/awfulclaw_mcp/gcal.py`:

```python
@mcp.tool()
def gcal_create(
    title: str,
    start: str,
    end: str,
    description: str = "",
    calendar_id: str = "primary",
) -> str:
    """Create a Google Calendar event.

    Args:
        title: Event title
        start: ISO 8601 start datetime (e.g. "2026-04-01T10:00:00Z")
        end: ISO 8601 end datetime (e.g. "2026-04-01T11:00:00Z")
        description: Optional event description
        calendar_id: Calendar to create in (default: "primary")
    """
    try:
        service = _get_service()
        body: dict[str, object] = {
            "summary": title,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if description:
            body["description"] = description
        event = service.events().insert(calendarId=calendar_id, body=body).execute()
        return f"[Created event: id={event['id']}]"
    except Exception as exc:
        return f"[gcal error: {exc}]"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_gcal_create_returns_event_id app/tests/test_mcp_gcal.py::test_gcal_create_passes_description app/tests/test_mcp_gcal.py::test_gcal_create_handles_error -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/awfulclaw_mcp/gcal.py app/tests/test_mcp_gcal.py
git commit -m "feat: add gcal_create MCP tool"
```

---

### Task 5: `gcal_update` Tool

**Files:**
- Modify: `app/awfulclaw_mcp/gcal.py`
- Modify: `app/tests/test_mcp_gcal.py`

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_mcp_gcal.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_gcal_update_title app/tests/test_mcp_gcal.py::test_gcal_update_skips_empty_fields app/tests/test_mcp_gcal.py::test_gcal_update_handles_error -v
```

Expected: FAIL — `gcal_update` is not defined.

- [ ] **Step 3: Implement `gcal_update`**

Add after `gcal_create` in `app/awfulclaw_mcp/gcal.py`:

```python
@mcp.tool()
def gcal_update(
    event_id: str,
    title: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    calendar_id: str = "primary",
) -> str:
    """Update an existing Google Calendar event. Only provided fields are changed.

    Args:
        event_id: ID of the event to update
        title: New title (omit to keep existing)
        start: New ISO 8601 start datetime (omit to keep existing)
        end: New ISO 8601 end datetime (omit to keep existing)
        description: New description (omit to keep existing)
        calendar_id: Calendar containing the event (default: "primary")
    """
    try:
        service = _get_service()
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        if title:
            event["summary"] = title
        if start:
            event["start"] = {"dateTime": start}
        if end:
            event["end"] = {"dateTime": end}
        if description:
            event["description"] = description
        service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
        return f"[Updated event: id={event_id}]"
    except Exception as exc:
        return f"[gcal error: {exc}]"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_gcal_update_title app/tests/test_mcp_gcal.py::test_gcal_update_skips_empty_fields app/tests/test_mcp_gcal.py::test_gcal_update_handles_error -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/awfulclaw_mcp/gcal.py app/tests/test_mcp_gcal.py
git commit -m "feat: add gcal_update MCP tool"
```

---

### Task 6: `gcal_delete` Tool

**Files:**
- Modify: `app/awfulclaw_mcp/gcal.py`
- Modify: `app/tests/test_mcp_gcal.py`

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_mcp_gcal.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/tests/test_mcp_gcal.py::test_gcal_delete_success app/tests/test_mcp_gcal.py::test_gcal_delete_custom_calendar app/tests/test_mcp_gcal.py::test_gcal_delete_handles_error -v
```

Expected: FAIL — `gcal_delete` is not defined.

- [ ] **Step 3: Implement `gcal_delete`**

Add after `gcal_update` in `app/awfulclaw_mcp/gcal.py`:

```python
@mcp.tool()
def gcal_delete(event_id: str, calendar_id: str = "primary") -> str:
    """Delete a Google Calendar event.

    Args:
        event_id: ID of the event to delete
        calendar_id: Calendar containing the event (default: "primary")
    """
    try:
        service = _get_service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return f"[Deleted event: id={event_id}]"
    except Exception as exc:
        return f"[gcal error: {exc}]"
```

- [ ] **Step 4: Run all gcal tests**

```bash
uv run pytest app/tests/test_mcp_gcal.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/awfulclaw_mcp/gcal.py app/tests/test_mcp_gcal.py
git commit -m "feat: add gcal_delete MCP tool"
```

---

### Task 7: Register Server and Update Docs

**Files:**
- Modify: `config/mcp_servers.json`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add gcal entry to `config/mcp_servers.json`**

Add the following entry to the `"servers"` array in `config/mcp_servers.json` (after the `imap` entry):

```json
{
  "name": "gcal",
  "command": "uv",
  "args": [
    "run",
    "python",
    "-m",
    "awfulclaw_mcp.gcal"
  ],
  "env": {
    "GOOGLE_CLIENT_SECRET_PATH": "${GOOGLE_CLIENT_SECRET_PATH}"
  },
  "env_required": [
    "GOOGLE_CLIENT_SECRET_PATH"
  ]
}
```

- [ ] **Step 2: Update `CLAUDE.md` Optional env vars section**

Add `GOOGLE_CLIENT_SECRET_PATH` to the Optional section of the env vars block in `CLAUDE.md`:

```
GOOGLE_CLIENT_SECRET_PATH=/path/to/client_secret.json  # required for Google Calendar MCP server
```

And add a new **Google Calendar setup** section to CLAUDE.md after the existing env vars block:

```markdown
### Google Calendar setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Create an OAuth 2.0 Client ID (Desktop app), download the JSON
3. Set `GOOGLE_CLIENT_SECRET_PATH=/path/to/downloaded.json` in `.env`
4. Run the one-time auth flow:
   ```bash
   uv run python -m awfulclaw_mcp.gcal --auth
   ```
   This opens a browser, completes the OAuth consent, and saves the token to
   `~/.config/awfulclaw/gcal_token.json`. The agent refreshes the token automatically.
```

- [ ] **Step 3: Run the full test suite to confirm nothing is broken**

```bash
uv run pytest
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add config/mcp_servers.json CLAUDE.md
git commit -m "feat: register gcal MCP server and document setup"
```
