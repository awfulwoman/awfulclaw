# awfulclaw

## Overview

awfulclaw is an autonomous AI agent that runs a poll-and-event loop, communicates via Telegram, and responds using Claude. Between messages it proactively checks in based on stored context and fires any scheduled tasks. Memory is stored as Markdown files and a SQLite database under `memory/` — Claude writes files by embedding `<memory:write>` blocks in its replies, which the loop intercepts and strips before sending. Structured data (facts, people, schedules) lives in `memory/awfulclaw.db`.

## Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)
- Claude CLI installed and authenticated (`claude` command available)

## Telegram Setup

1. Message [@BotFather](https://t.me/botfather) on Telegram and run `/newbot` to create a bot — copy the token it gives you
2. Start a conversation with your new bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id`
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env`

## Installation

```bash
git clone https://github.com/awfulwoman/awfulclaw.git
cd awfulclaw
uv sync
```

## Configuration

Create a `.env` file in the project root:

```env
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
```

Authentication comes from the `claude` CLI — no API key needed. Run `claude` and sign in if you haven't already.

Optional settings:

```env
AWFULCLAW_MODEL=claude-sonnet-4-6   # default
AWFULCLAW_POLL_INTERVAL=5           # seconds between polls
AWFULCLAW_IDLE_INTERVAL=60          # seconds between proactive idle checks
AWFULCLAW_BRIEFING_TIME=08:00       # daily briefing time in HH:MM UTC (omit to disable)

# IMAP MCP server (optional — enables email checking)
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USER=you@example.com
IMAP_PASSWORD=yourpassword
```

## Running

```bash
uv run python -m awfulclaw
```

Stop with **Ctrl-C**.

## Running as a Service (macOS)

Requires a `.env` file in the project root before installing.

```bash
bash scripts/install-service.sh
```

This copies the launchd plist to `~/Library/LaunchAgents/`, starts the agent, and configures it to start automatically on login and restart on crash. Logs are written to:

- `logs/awfulclaw.out.log`
- `logs/awfulclaw.err.log`

Manual stop/start:

```bash
launchctl unload ~/Library/LaunchAgents/ai.awfulclaw.agent.plist
launchctl load  ~/Library/LaunchAgents/ai.awfulclaw.agent.plist
```

Uninstall:

```bash
bash scripts/uninstall-service.sh
```

## Memory

The `memory/` folder stores the agent's persistent context:

- `memory/SOUL.md` — personality and instructions (edit to customise the agent)
- `memory/USER.md` — user profile (updated by the agent over time)
- `memory/awfulclaw.db` — SQLite database (facts, people, schedules)
- `memory/tasks/` — open task files with Markdown checkboxes

Claude writes new memories by including `<memory:write path="...">...</memory:write>` blocks in its replies — the loop intercepts these, writes the files, and strips the tags before sending.

## MCP Servers

Claude has access to tools via MCP servers declared in `config/mcp_servers.json`:

- **memory_write** — writes files to `memory/`
- **memory_search** — searches memory files and the database
- **schedule** — creates and deletes named scheduled tasks. Schedules persist in the database and fire their prompt on the configured cron.
- **imap** — fetches unread emails from the configured IMAP account (requires IMAP env vars)

To add a new MCP server, add an entry to `config/mcp_servers.json`.
