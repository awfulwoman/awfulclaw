# awfulclaw

## Overview

awfulclaw is an autonomous iMessage AI agent. It runs a poll-and-event loop on macOS, receives and sends iMessages, and responds using Claude. Between messages it can proactively check in based on stored context. All memory is stored as Markdown files under `memory/` — Claude writes to them by embedding `<memory:write>` blocks in its replies, which the loop intercepts and strips before sending.

## Requirements

- macOS (tested on Ventura+)
- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)
- Claude CLI installed and authenticated (`claude` command available)
- Messages.app signed in with your Apple ID

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
AWFULCLAW_PHONE=+15555550100   # required: phone number or Apple ID of your iMessage contact
```

Authentication comes from the `claude` CLI — no API key needed. Run `claude` and sign in if you haven't already.

Optional settings:

```env
AWFULCLAW_MODEL=claude-sonnet-4-6   # default
AWFULCLAW_POLL_INTERVAL=5           # seconds between iMessage polls
AWFULCLAW_IDLE_INTERVAL=60          # seconds between proactive idle checks
```

## Running

```bash
python -m awfulclaw
```

Stop with **Ctrl-C**.

## Memory

The `memory/` folder stores the agent's persistent context as Markdown files, organized into subdirectories: `people/`, `tasks/`, `facts/`, and `conversations/`. Claude writes new memories by including `<memory:write path="...">...</memory:write>` blocks in its replies — the agent loop intercepts these blocks, writes the files to disk, and strips them from the outgoing message so the contact never sees them.
