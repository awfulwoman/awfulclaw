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
    from dotenv import load_dotenv
    from google_auth_oauthlib.flow import InstalledAppFlow

    load_dotenv()
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


if __name__ == "__main__":
    if "--auth" in sys.argv:
        _run_auth()
    else:
        mcp.run()
