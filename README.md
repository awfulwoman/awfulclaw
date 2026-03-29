# awfulclaw

## Overview

awfulclaw is an autonomous AI agent that runs a poll-and-event loop, communicates via Telegram or iMessage, and responds using Claude. Between messages it proactively checks in based on stored context and fires any scheduled tasks. All memory is stored as Markdown files under `memory/` — Claude writes to them by embedding `<memory:write>` blocks in its replies, which the loop intercepts and strips before sending.

## Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)
- Claude CLI installed and authenticated (`claude` command available)
- **iMessage only:** macOS (tested on Ventura+) with Messages.app signed in

## Telegram Setup

1. Message [@BotFather](https://t.me/botfather) on Telegram and run `/newbot` to create a bot — copy the token it gives you
2. Start a conversation with your new bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id`
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env`

## iMessage Setup

1. Open **System Settings → Privacy & Security → Full Disk Access**
2. Add your terminal emulator (e.g. Terminal.app, iTerm2, Ghostty) to the list — Python needs this to read `~/Library/Messages/chat.db`
3. Open Messages.app and confirm you are signed in and can send/receive iMessages
4. Note the phone number or Apple ID of the contact you want the agent to talk to — this becomes `AWFULCLAW_PHONE`

## Installation

```bash
git clone https://github.com/awfulwoman/awfulclaw.git
cd awfulclaw
uv sync
```

## Configuration

Create a `.env` file in the project root:

```env
# Telegram (default channel)
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>

# iMessage (set AWFULCLAW_CHANNEL=imessage to use instead)
# AWFULCLAW_CHANNEL=imessage
# AWFULCLAW_PHONE=+15555550100
```

Authentication comes from the `claude` CLI — no API key needed. Run `claude` and sign in if you haven't already.

Optional settings:

```env
AWFULCLAW_MODEL=claude-sonnet-4-6   # default
AWFULCLAW_POLL_INTERVAL=5           # seconds between polls
AWFULCLAW_IDLE_INTERVAL=60          # seconds between proactive idle checks

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

## Memory

The `memory/` folder stores the agent's persistent context as Markdown files, organized into subdirectories: `people/`, `tasks/`, `facts/`, and `conversations/`. Claude writes new memories by including `<memory:write path="...">...</memory:write>` blocks in its replies — the loop intercepts these, writes the files, and strips the tags before sending.

## Skills

Claude can invoke built-in skills by including special tags in its replies:

- **`<skill:imap/>`** — fetches unread emails from the configured IMAP account and injects them into the conversation. Requires IMAP env vars to be set.
- **`<skill:schedule action="create" name="..." cron="...">`** — creates a recurring scheduled task. Example cron expressions: `0 9 * * *` (daily at 9am), `0 9 * * 1-5` (weekdays at 9am), `0 * * * *` (hourly).
- **`<skill:schedule action="delete" name="..."/>`** — deletes a named schedule.

Schedules persist in `memory/schedules.json`. When a schedule fires, Claude runs the associated prompt and sends the result to the active channel.
