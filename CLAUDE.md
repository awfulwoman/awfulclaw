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

The file watcher (`ai.awfulclaw.watcher`) monitors `awfulclaw/` and restarts the agent when core `.py` files change on the `main` branch (60s debounce, ignores `__pycache__` and `awfulclaw/modules/`). Module changes are hot-reloaded without a full restart.

## Architecture

The agent loop (`loop.py`) is the core. On each tick it:
1. Calls `connector.poll_new_messages()` — connector selected by `AWFULCLAW_CHANNEL`, instantiated in `config.get_connector()`
2. For each message: calls `context.build_system_prompt()`, calls `claude.chat()` via CLI subprocess, dispatches skill tags via the module registry, sends the cleaned reply via `connector.send_message()`
3. On idle ticks: calls `registry.check_for_changes()` (hot-reload), runs due schedules from `memory/schedules.json`, and sends the daily briefing if configured

**Connector** (`connector.py`) — `TelegramConnector` implements the `Connector` ABC. Telegram poll offset is persisted to `memory/.telegram_offset` to survive restarts.

**Claude invocation** (`claude.py`) — shells out to `claude --print --no-session-persistence --system-prompt ...`. Conversation history is formatted as plain text and passed via stdin. Each call is a fresh subprocess — there is no persistent session.

**System prompt** (`context.py`) — built fresh on every turn from `memory/SOUL.md` (personality/instructions), `memory/USER.md` (user profile), plus relevant facts, people, tasks, and schedules. Module skill documentation is injected automatically from the module registry.

**Module system** (`awfulclaw/modules/`) — skills are implemented as modules:
- Each module is a subpackage under `awfulclaw/modules/<name>/`
- Must expose `create_module() -> Module` in its `__init__.py`
- Implements the `Module` ABC from `awfulclaw/modules/base.py`
- The registry (`get_registry()`) auto-discovers all modules on startup and hot-reloads on idle ticks
- Built-in modules: `imap`, `schedule`, `search`, `web`, `module_generator`

**Adding a new module:**
1. Create `awfulclaw/modules/<name>/` with `__init__.py` (exporting `create_module()`) and `_<name>.py` (implementing `Module`)
2. Or use the agent skill: `<skill:create_module name="..." description="...">docs</skill:create_module>`
3. The registry picks it up on the next idle tick (hot-reload) — no restart needed

**Special reply tags** — intercepted and stripped before sending:
- `<memory:write path="...">content</memory:write>` — writes to `memory/<path>` (core, not a module)
- Module skill tags (e.g. `<skill:web query="..."/>`) — dispatched via the module registry

**Slash commands** (user or agent can send): `/tasks`, `/skills`, `/schedules`, `/restart`

**Memory** lives in `memory/` with subdirs `people/`, `tasks/`, `facts/`, `skills/`, `conversations/YYYY/MM/`. Schedules persist in `memory/schedules.json`.
