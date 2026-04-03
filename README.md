# awfulclaw

An autonomous AI agent that communicates via Telegram (and a REST API), invokes Claude via the `claude` CLI subprocess, and stores working memory in SQLite. Runs natively on a dedicated Mac Mini, supervised by launchd. No Docker, no API key — auth comes from the locally installed `claude` CLI.

## Requirements

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv)
- Claude CLI installed and authenticated (`claude` command available)

## Running

```bash
uv run python -m agent --connector telegram
uv run python -m agent --connector rest
uv run python -m agent --tcc-setup   # request macOS permissions
```

## Architecture

```
User (Telegram/REST)
    → Connector → Bus → Pipeline → Agent → Claude CLI
                                        ↓
                                   MCP Servers → Store (SQLite)
```

**Packages:**

| Package | Purpose |
|---------|---------|
| `agent/connectors/` | Telegram + REST transports |
| `agent/middleware/` | Rate limiting, slash commands, location, typing, invocation |
| `agent/handlers/` | Check-in, orientation, governance, knowledge flush |
| `agent/mcp/` | Tool servers (memory, schedule, calendar, contacts, email, weather, etc.) |
| `agent/store.py` | Unified SQLite layer with semantic search (sqlite-vec) |
| `agent/context.py` | Dynamic system prompt assembly |
| `agent/scheduler.py` | Cron + one-shot scheduling |
| `agent/agent.py` | Claude invocation and turn storage |

## Configuration

Copy `.env.example` to `.env` and fill in:

```
AWFULCLAW_MODEL=claude-opus-4-5
AWFULCLAW_TELEGRAM__BOT_TOKEN=...
AWFULCLAW_TELEGRAM__ALLOWED_CHAT_IDS=...
```

Agent personality and protocols live in `agent_config/`:

| File | Purpose |
|------|---------|
| `PERSONALITY.md` | Identity, behavior, constraints |
| `PROTOCOLS.md` | Communication rules, escalation |
| `USER.md` | User profile and preferences |
| `CHECKIN.md` | Idle/check-in prompts |

## Documentation

| Document | Purpose |
|----------|---------|
| `DESIGN.md` | Original architecture spec — historical reference |
| `PHILOSOPHY.md` | Design values, data philosophy, governance model |
| `CLAUDE.md` | Guidance for Claude Code when working in this repo |

## Testing

```bash
uv run pytest
```
