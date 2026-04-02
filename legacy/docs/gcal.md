# Google Calendar Integration

Gives the agent full CRUD access to Google Calendar via four MCP tools: `gcal_list`, `gcal_create`, `gcal_update`, `gcal_delete`.

## Setup

### 1. Create a Google Cloud project and enable the Calendar API

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Select or create a project
3. **APIs & Services → Library** — search for "Google Calendar API" and enable it

### 2. Create OAuth credentials

1. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
2. Application type: **Desktop app** — name it anything (e.g. `awfulclaw`)
3. Click **Download JSON** and save it somewhere permanent, e.g.:
   ```
   ~/.config/awfulclaw/client_secret.json
   ```

### 3. Configure the env var

Add to your `.env`:

```
GOOGLE_CLIENT_SECRET_PATH=/path/to/client_secret.json
```

### 4. Run the one-time auth flow

```bash
uv run python -m awfulclaw_mcp.gcal --auth
```

This opens a browser, completes the OAuth consent screen, and saves the token to `~/.config/awfulclaw/gcal_token.json`. The agent refreshes the token automatically going forward.

## Tools

| Tool | Description |
|------|-------------|
| `gcal_list(start, end, calendar_id?)` | List events in an ISO 8601 datetime range |
| `gcal_create(title, start, end, description?, calendar_id?)` | Create an event |
| `gcal_update(event_id, title?, start?, end?, description?, calendar_id?)` | Update fields on an existing event |
| `gcal_delete(event_id, calendar_id?)` | Delete an event |

All datetimes are ISO 8601 (e.g. `2026-04-01T10:00:00Z`). `calendar_id` defaults to `"primary"`.

## Notes

- The token is stored at `~/.config/awfulclaw/gcal_token.json` — outside `memory/` so the agent cannot read it directly
- If the server is skipped at startup (missing env var), the agent will say so
- To re-authenticate, delete the token file and re-run `--auth`
