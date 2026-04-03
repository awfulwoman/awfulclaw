# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**awfulclaw** — an autonomous AI agent that communicates via Telegram (and a REST API), invokes Claude via the `claude` CLI subprocess, and stores working memory in SQLite. Runs natively on a dedicated Mac Mini, supervised by launchd. No Docker, no API key — auth comes from the locally installed `claude` CLI.

## Status

Implementation is complete. `docs/DESIGN.md` is kept as a historical reference showing the original architecture spec; the actual source of truth is the code in `agent/`.

## Layout

```
agent/              # main application
profile/            # human-editable config: PERSONALITY.md, PROTOCOLS.md, USER.md, CHECKIN.md
config/             # MCP server definitions and skill files
docs/               # DESIGN.md (historical spec), PHILOSOPHY.md (design values)
tests/              # pytest test suite
CLAUDE.md           # this file
```

## Key documents

- **`docs/PHILOSOPHY.md`** — design values: data philosophy, policy layers, governance model, self-modification limits. Still authoritative for design decisions.
- **`docs/DESIGN.md`** — the original implementation spec. Useful historical context but may diverge from the actual implementation.

## Architecture

```
User (Telegram/REST)
    → Connector → Bus → Pipeline → Agent → Claude CLI
                                        ↓
                                   MCP Servers → Store (SQLite)
```

**Core modules:**

| Module | Role |
|--------|------|
| `agent/main.py` | Entry point; wires all components |
| `agent/agent.py` | Claude invocation, context assembly, turn storage |
| `agent/bus.py` | Async pub-sub event bus |
| `agent/pipeline.py` | Middleware chain |
| `agent/store.py` | SQLite layer (facts, people, conversations, schedules, kv) |
| `agent/context.py` | Dynamic system prompt assembly with semantic search |
| `agent/scheduler.py` | Cron + one-shot scheduling |
| `agent/cron.py` | Cron expression parsing / scheduling helpers |
| `agent/config.py` | Config loading |
| `agent/claude_client.py` | `claude` CLI subprocess wrapper |
| `agent/connectors/` | Telegram + REST transports |
| `agent/middleware/` | Rate limit, secret capture, location, slash commands, typing, invoke |
| `agent/handlers/` | Check-in, orientation, governance, knowledge flush, schedule |
| `agent/mcp/` | Tool servers: memory, schedule, eventkit (calendar), contacts, imap (email), weather, owntracks (location), skills, file_read, env_manager |

## Working in this codebase

- Read the code directly — it's the source of truth.
- Run tests with `uv run pytest`.
- macOS-specific features (EventKit, Contacts) require `pyobjc` and TCC permissions; use `--tcc-setup` to request them.
- The `claude` CLI must be installed and authenticated for agent invocation to work.
- `.env` is blocked at the MCP capability level — the agent cannot read it.
