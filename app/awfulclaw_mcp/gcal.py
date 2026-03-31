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
