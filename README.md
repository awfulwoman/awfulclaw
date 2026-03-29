# awfulclaw

## Overview

awfulclaw is an autonomous AI agent that runs a poll-and-event loop, communicates via Telegram, and responds using Claude. Between messages it proactively checks in based on stored context and fires any scheduled tasks. All memory is stored as Markdown files under `memory/` — Claude writes to them by embedding `<memory:write>` blocks in its replies, which the loop intercepts and strips before sending.

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

# IMAP skill (optional — enables email checking via <skill:imap/>)
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

The `memory/` folder stores the agent's persistent context as Markdown files, organized into subdirectories: `people/`, `tasks/`, `facts/`, and `conversations/`. Claude writes new memories by including `<memory:write path="...">...</memory:write>` blocks in its replies — the loop intercepts these, writes the files, and strips the tags before sending.

## Skills

Claude can invoke built-in skills by including special tags in its replies:

- **`<skill:imap/>`** — fetches unread emails from the configured IMAP account and injects them into the conversation. Requires IMAP env vars to be set.
- **`<skill:schedule action="create" name="..." cron="...">`** — creates a recurring scheduled task. Example cron expressions: `0 9 * * *` (daily at 9am), `0 9 * * 1-5` (weekdays at 9am), `0 * * * *` (hourly).
- **`<skill:schedule action="delete" name="..."/>`** — deletes a named schedule.

Schedules persist in `memory/schedules.json`. When a schedule fires, Claude runs the associated prompt and sends the result to the active channel.
