# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**awfulclaw** — an autonomous iMessage AI agent built with Python and the Anthropic SDK. It runs a poll+event loop, responds to iMessages via Claude, and stores memory as Markdown files under `memory/`.

## Setup

```bash
uv sync                  # install deps
cp .env.example .env     # then fill in values (if example exists, else create .env)
```

Required env vars (in `.env`):
```
ANTHROPIC_API_KEY=...
AWFULCLAW_PHONE=+15555550100   # iMessage contact to converse with
```

Optional:
```
AWFULCLAW_MODEL=claude-sonnet-4-6   # default
AWFULCLAW_POLL_INTERVAL=5           # seconds between iMessage polls
AWFULCLAW_IDLE_INTERVAL=60          # seconds between proactive idle checks
```

## Running

```bash
python -m awfulclaw      # starts the agent loop, Ctrl-C to stop
```

Requires macOS with the Messages app signed in (uses `osascript` to read/send iMessages).

## Development

```bash
uv run pytest                        # all tests
uv run pytest tests/test_memory.py   # single file
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv run pyright                       # typecheck
```

## Architecture

The agent loop (`loop.py`) is the entry point. On each tick it:
1. Polls `imessage.poll_new_messages()` for new inbound texts
2. Calls `context.build_system_prompt()` to assemble memory into the system prompt
3. Calls `claude.chat()` with conversation history + system prompt
4. Parses `<memory:write path="...">...</memory:write>` blocks out of the reply, writes them to disk via `memory.write()`, strips the blocks from the outgoing text
5. Sends the cleaned reply via `imessage.send_message()`
6. On idle ticks, runs a proactive check asking Claude if anything in memory needs attention

**Memory** lives in `memory/` with subdirs `people/`, `tasks/`, `facts/`, `conversations/`. Claude writes to memory by embedding `<memory:write>` blocks in its replies — the loop intercepts and strips them before sending.

**iMessage I/O** is macOS-only via `osascript` subprocesses querying `~/Library/Messages/chat.db` (reads) and the Messages app (sends).
