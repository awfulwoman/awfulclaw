# Google Calendar MCP Integration

**Date:** 2026-03-31

## Overview

Add a Google Calendar MCP server to awfulclaw, following the same pattern as `imap.py`. The agent gains full CRUD access to Google Calendar via four MCP tools. Auth is handled once manually via a CLI command; the token is stored outside the memory directory so the agent cannot read it.

## Architecture

A new `app/awfulclaw_mcp/gcal.py` MCP server built on `google-api-python-client` and `google-auth-oauthlib`, registered in `config/mcp_servers.json`.

- **Auth token:** `~/.config/awfulclaw/gcal_token.json` — outside `memory/`, not visible to the agent
- **Client secret:** path provided via `GOOGLE_CLIENT_SECRET_PATH` env var (JSON downloaded from Google Cloud Console)
- **Scopes:** `https://www.googleapis.com/auth/calendar`
- **Token refresh:** handled automatically by the Google auth library on each call

The server is skipped gracefully if `GOOGLE_CLIENT_SECRET_PATH` is not set (same `env_required` mechanism as `imap`).

## One-Time Auth Setup

```bash
# 1. Download OAuth client secret from Google Cloud Console
#    (Credentials → OAuth 2.0 Client IDs → Download JSON)

# 2. Add to .env:
GOOGLE_CLIENT_SECRET_PATH=/path/to/client_secret.json

# 3. Run the auth flow once:
uv run python -m awfulclaw_mcp.gcal --auth
# Opens browser → complete OAuth consent → token saved to ~/.config/awfulclaw/gcal_token.json
```

## MCP Tools

All tools accept an optional `calendar_id` parameter (defaults to `"primary"`). Datetimes are ISO 8601 strings. Errors are returned as `[gcal error: ...]` strings.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `gcal_list` | `start`, `end`, `calendar_id?` | List events in a datetime range. Returns id, summary, start, end per event. |
| `gcal_create` | `title`, `start`, `end`, `description?`, `calendar_id?` | Create a new event. Returns the created event id. |
| `gcal_update` | `event_id`, `title?`, `start?`, `end?`, `description?`, `calendar_id?` | Update fields on an existing event. |
| `gcal_delete` | `event_id`, `calendar_id?` | Delete an event. |

## Dependencies

Add to `pyproject.toml`:
- `google-api-python-client`
- `google-auth-oauthlib`

## config/mcp_servers.json Entry

```json
{
  "name": "gcal",
  "command": "uv",
  "args": ["run", "python", "-m", "awfulclaw_mcp.gcal"],
  "env": {
    "GOOGLE_CLIENT_SECRET_PATH": "${GOOGLE_CLIENT_SECRET_PATH}"
  },
  "env_required": ["GOOGLE_CLIENT_SECRET_PATH"]
}
```

## Error Handling

- Missing env var → server skipped at startup (existing registry behaviour)
- Token missing (auth not run) → tools return `[gcal error: not authenticated — run: uv run python -m awfulclaw_mcp.gcal --auth]`
- API errors → return `[gcal error: <message>]`

## CLAUDE.md Update

Add a `gcal` section to the Optional env vars table and document the one-time auth setup step.
