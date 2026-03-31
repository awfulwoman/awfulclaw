# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**awfulclaw** — an autonomous AI agent that runs a poll+event loop, communicates via Telegram, and stores memory as Markdown files and a SQLite database under `memory/`. Claude is invoked via the `claude` CLI subprocess (no API key required).

## Setup

```bash
uv sync --extra dev   # install deps + dev tools
```

Required env vars (in `.env`):
```
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<chat-id>
```

Optional:
```
AWFULCLAW_MODEL=claude-sonnet-4-6   # default
AWFULCLAW_POLL_INTERVAL=5           # seconds between polls
AWFULCLAW_IDLE_INTERVAL=60          # seconds between idle checks
AWFULCLAW_IDLE_NUDGE_COOLDOWN=86400 # min seconds between unsolicited idle messages (default 24h)
AWFULCLAW_BRIEFING_TIME=08:00       # daily briefing in HH:MM UTC (omit to disable)
AWFULCLAW_EMAIL_CHECK_INTERVAL=300  # seconds between proactive email checks (default 5m, requires IMAP)
IMAP_HOST=imap.example.com          # required to use the imap MCP server
IMAP_PORT=993
IMAP_USER=you@example.com
IMAP_PASSWORD=...
GOOGLE_CLIENT_SECRET_PATH=/path/to/client_secret.json  # required for Google Calendar MCP server
OWNTRACKS_URL=https://your-recorder.example.com  # required to use OwnTracks MCP server
OWNTRACKS_USER=charlie                            # default: charlie
OWNTRACKS_DEVICE=iphone                           # default: iphone
HASS_URL=https://your-ha.example.com/api/mcp      # required to use Home Assistant MCP server
HASS_TOKEN=...                                    # long-lived Home Assistant access token
GITHUB_PERSONAL_ACCESS_TOKEN=...                  # required to use GitHub MCP server
```

No API key needed — auth comes from the locally installed `claude` CLI.

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

## Running

```bash
uv run python -m awfulclaw      # starts the agent loop, Ctrl-C to stop
```

## Development

```bash
uv run pytest                             # all tests
uv run pytest app/tests/test_memory.py   # single file
uv run ruff check .                       # lint
uv run ruff format .                      # format
uv run --with pyright pyright             # typecheck
```

## Service

The app runs as a launchd service (macOS). Scripts are in `scripts/`:

```bash
bash scripts/install-service.sh    # install + start agent and file watcher
bash scripts/uninstall-service.sh  # stop and remove
bash scripts/restart-service.sh    # manual restart
```

The file watcher (`ai.awfulclaw.watcher`) monitors `app/awfulclaw/` and restarts the agent when core `.py` files change on the `main` branch (60s debounce, ignores `__pycache__`).

## Layout

```
app/
  awfulclaw/       # main agent package
  awfulclaw_mcp/   # MCP server implementations
  tests/           # test suite
config/
  mcp_servers.json # declarative MCP server registry
memory/            # runtime state (gitignored)
scripts/           # install/uninstall/restart helpers
```

## Architecture

The agent loop (`loop.py`) is the core. On each tick it:
1. Calls `connector.poll_new_messages()` — connector selected by `AWFULCLAW_CHANNEL`, instantiated in `config.get_connector()`
2. For each message: calls `context.build_system_prompt()`, calls `claude.chat()` via CLI subprocess with MCP servers attached, sends the cleaned reply via `connector.send_message()`
3. On idle ticks: runs due schedules from the database and sends the daily briefing if configured

**Connector** (`connector.py`) — `TelegramConnector` implements the `Connector` ABC. Telegram poll offset is persisted to `memory/.telegram_offset` to survive restarts.

**Claude invocation** (`claude.py`) — shells out to `claude --print --no-session-persistence --system-prompt ...`. Conversation history is formatted as plain text and passed via stdin. Each call is a fresh subprocess — there is no persistent session. MCP servers listed in `config/mcp_servers.json` are attached via `--mcp-config`.

**System prompt** (`context.py`) — built fresh on every turn from `memory/SOUL.md` (personality/instructions), `memory/USER.md` (user profile), plus relevant facts, people, tasks, and schedules loaded from the database and memory files.

**MCP servers** (`app/awfulclaw_mcp/`) — tool access for Claude is provided by MCP servers:
- `memory_write` — writes files to `memory/`
- `memory_search` — searches memory files and the database
- `schedule` — creates and deletes named schedules
- `imap` — fetches unread emails (requires IMAP env vars)

MCP server registration is declarative: `config/mcp_servers.json` lists each server. The registry (`awfulclaw_mcp/registry.py`) loads and hot-reloads this config.

**Adding a new MCP server:**
1. Create a new module in `app/awfulclaw_mcp/` (e.g. `app/awfulclaw_mcp/mytool.py`) implementing an MCP server
2. Add an entry to `config/mcp_servers.json` with `name`, `command`, `args`, and optionally `env` / `env_required`
3. The registry picks it up on the next idle tick — no restart needed

**Special reply tags** — intercepted and stripped before sending:
- `<memory:write path="...">content</memory:write>` — writes to `memory/<path>` (core, not an MCP server)

**Slash commands** (user or agent can send): `/schedules`, `/restart`

**Memory** lives in `memory/` (gitignored at runtime):
- `memory/SOUL.md` — personality and instructions
- `memory/USER.md` — user profile
- `memory/awfulclaw.db` — SQLite database (facts, people, schedules)
- `memory/tasks/` — open task files (Markdown with checkboxes)
- `memory/.telegram_offset` — Telegram poll offset
