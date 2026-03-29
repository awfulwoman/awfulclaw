# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**awfulclaw** — an autonomous AI agent that runs a poll+event loop, communicates via Telegram, and stores memory as Markdown files under `memory/`. Claude is invoked via the `claude` CLI subprocess (no API key required).

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
AWFULCLAW_BRIEFING_TIME=08:00       # daily briefing in HH:MM UTC (omit to disable)
IMAP_HOST=imap.example.com          # required to use <skill:imap/>
IMAP_PORT=993
IMAP_USER=you@example.com
IMAP_PASSWORD=...
```

No API key needed — auth comes from the locally installed `claude` CLI.

## Running

```bash
uv run python -m awfulclaw      # starts the agent loop, Ctrl-C to stop
```

## Development

```bash
uv run pytest                             # all tests
uv run pytest tests/test_memory.py        # single file
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

The file watcher (`ai.awfulclaw.watcher`) monitors `awfulclaw/` and restarts the agent when `.py` files change on the `main` branch (60s debounce, ignores `__pycache__`). On restart the agent sends a context-aware message explaining why it restarted.

## Architecture

The agent loop (`loop.py`) is the core. On each tick it:
1. Calls `connector.poll_new_messages()` — connector selected by `AWFULCLAW_CHANNEL`, instantiated in `config.get_connector()`
2. For each message: calls `context.build_system_prompt()`, calls `claude.chat()` via CLI subprocess, intercepts special tags in the reply (see below), sends the cleaned reply via `connector.send_message()`
3. On idle ticks: runs a silent heartbeat check (`memory/HEARTBEAT.md`), fires any due schedules from `memory/schedules.json`, and sends the daily briefing if configured

**Connector** (`connector.py`) — `TelegramConnector` implements the `Connector` ABC. Telegram poll offset is persisted to `memory/.telegram_offset` to survive restarts.

**Claude invocation** (`claude.py`) — shells out to `claude --print --no-session-persistence --system-prompt ...`. Conversation history is formatted as plain text and passed via stdin. Each call is a fresh subprocess — there is no persistent session.

**System prompt** (`context.py`) — built fresh on every turn from `memory/SOUL.md` (personality/instructions), `memory/USER.md` (user profile), plus relevant facts, people, tasks, skills, and schedules. Editing `SOUL.md` takes effect on the next message.

**Special reply tags** — intercepted and stripped before sending:
- `<memory:write path="...">content</memory:write>` — writes to `memory/<path>` (the `memory/` prefix is optional)
- `<skill:imap/>` — fetches unread emails via IMAP, injects results as a follow-up user message
- `<skill:web query="..."/>` — web search, results injected as follow-up
- `<skill:search query="..."/>` — searches all memory files, results injected as follow-up
- `<skill:schedule action="create" name="..." cron="..." [condition="cmd"]>prompt</skill:schedule>` — creates/updates a schedule; optional `condition` is a shell command that must print `{"wakeAgent": true/false}`
- `<skill:schedule action="create" name="..." at="ISO-datetime">prompt</skill:schedule>` — one-off reminder
- `<skill:schedule action="delete" name="..."/>` — deletes a schedule

**Slash commands** (user or agent can send): `/tasks`, `/skills`, `/schedules`, `/restart`

**Memory** lives in `memory/` with subdirs `people/`, `tasks/`, `facts/`, `skills/`, `conversations/YYYY/MM/`. Schedules persist in `memory/schedules.json`.
