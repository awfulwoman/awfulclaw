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

## Architecture

The agent loop (`loop.py`) is the core. On each tick it:
1. Calls `connector.poll_new_messages()` — active connector is selected by `AWFULCLAW_CHANNEL` and instantiated in `config.get_connector()`
2. For each message: calls `context.build_system_prompt()`, calls `claude.chat()` via CLI subprocess, intercepts special tags in the reply (see below), sends the cleaned reply via `connector.send_message()`
3. On idle ticks: proactive Claude check + fires any due schedules from `memory/schedules.json`

**Connector** (`connector.py`) — `TelegramConnector` implements the `Connector` ABC (`poll_new_messages`, `send_message`, `primary_recipient`).

**Claude invocation** (`claude.py`) — shells out to `claude --print --no-session-persistence --system-prompt ...`. Conversation history is formatted as plain text and passed via stdin.

**Special reply tags** — the loop intercepts these before sending, strips them from the outgoing message:
- `<memory:write path="...">content</memory:write>` — writes a memory file
- `<skill:imap/>` — fetches unread emails via IMAP, injects results as a follow-up user message
- `<skill:schedule action="create" name="..." cron="...">prompt</skill:schedule>` — creates a schedule
- `<skill:schedule action="delete" name="..."/>` — deletes a schedule

**Memory** lives in `memory/` with subdirs `people/`, `tasks/`, `facts/`, `conversations/`. Schedules persist in `memory/schedules.json`.
