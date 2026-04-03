# Architecture

Current-state description of how awfulclaw is structured. Reflects the code in `agent/` as of the time of writing — if in doubt, read the source.

## Message flow

```
User (Telegram / REST API)
  │
  ▼
Connector            telegram.py / rest.py
  │  on_message()
  ▼
Bus                  bus.py  (async pub-sub)
  │  InboundEvent
  ▼
Pipeline             pipeline.py  (middleware chain)
  │
  ├─ RateLimitMiddleware       one request at a time per channel
  ├─ SecretCaptureMiddleware   intercepts secret:// values → store.kv
  ├─ LocationMiddleware        writes location from kv into event context
  ├─ SlashCommandMiddleware    handles /restart, /schedules; short-circuits
  ├─ TypingMiddleware          sends typing indicator; keeps it alive
  └─ InvokeMiddleware          calls Agent, posts OutboundEvent to Bus
       │
       ▼
     Agent            agent.py
       │  builds system prompt (context.py)
       │  calls claude CLI subprocess (claude_client.py)
       │  Claude invokes MCP tools mid-turn
       │  stores turn in conversations table
       ▼
     OutboundEvent → Bus → Connector.send() → User
```

## Background tasks

These run concurrently in the main `asyncio.TaskGroup`:

| Task | Description |
|------|-------------|
| `bus.run()` | Dispatches queued events to subscribers |
| `connector.start()` | Polls / listens for inbound messages (one per connector) |
| `scheduler.run()` | Fires `ScheduleEvent` for due cron/one-shot schedules |
| `checkin_loop()` | Calls `CheckinHandler` every 60s (proactive messages) |
| `orientation_task()` | Runs once at startup to orient the agent |
| `mcp.watch_config()` | Hot-reloads `mcp_servers.json` every 10s |
| `_shutdown_watcher()` | Converts SIGTERM → `_ShutdownRequested` for clean exit |

## Components

### Connectors (`agent/connectors/`)

Adapters between the outside world and the internal event bus. Each connector implements `start(on_message)` and `send(channel, message)`.

- **TelegramConnector** — polls the Telegram Bot API; restricts to `allowed_chat_ids`.
- **RESTConnector** — minimal HTTP server for programmatic access.

### Bus (`agent/bus.py`)

Simple async pub-sub. Subscribers register for an event type; `bus.post(event)` dispatches to all matching subscribers as background tasks.

### Pipeline (`agent/pipeline.py`)

Ordered middleware chain. Each middleware receives `(event, next)` and can short-circuit (slash commands) or pass through. Implemented as a composed async function.

### Agent (`agent/agent.py`)

Orchestrates a single Claude turn:
1. Assembles system prompt via `context.py` (profile files + semantic memory search + kv facts like location/timezone)
2. Calls the `claude` CLI subprocess via `claude_client.py`
3. Claude may invoke MCP tools during the turn (handled transparently by the CLI)
4. Stores the completed turn in `conversations`

### Store (`agent/store.py`)

SQLite via `aiosqlite`. Tables:

| Table | Contents |
|-------|----------|
| `facts` | Key/value semantic memory with embeddings |
| `people` | Named entities with embeddings |
| `conversations` | Turn history (channel, role, text, timestamp) |
| `schedules` | Cron and one-shot schedule definitions |
| `kv` | Simple key/value store (location, timezone, secrets) |

Embeddings use `sqlite-vec` for cosine similarity search.

### MCP Servers (`agent/mcp/`)

Each server is a standalone stdio subprocess exposing tools to Claude. Managed by `MCPClient` (`agent/mcp/__init__.py`), which hot-reloads from `config/mcp_servers.json`.

| Server | Tools |
|--------|-------|
| `memory` | `memory_write`, `memory_search` |
| `schedule` | `schedule_create`, `schedule_delete`, `schedule_list` |
| `eventkit` | Calendar + Reminders via macOS EventKit |
| `contacts` | macOS Contacts via CNContactStore |
| `imap` | `email_read`, `email_search`, `email_unread` |
| `weather` | Current conditions and forecast |
| `owntracks` | `location_get`, `owntracks_update` |
| `obsidian` | `note_write`, `note_append`, `note_read`, `note_search`, `note_list` |
| `skills` | Exposes skill files from `config/skills/` as tools |
| `file_read` | Safe file read with path traversal guard |
| `env_manager` | Read/write non-secret env configuration |

### Handlers (`agent/handlers/`)

Higher-level behaviours triggered outside of normal user turns:

- **CheckinHandler** — decides if the agent should proactively message the user (runs every 60s)
- **OrientationHandler** — runs once at startup; gives agent context about the current state of the world
- **ScheduleHandler** — handles `ScheduleEvent` from the scheduler; invokes the agent with the schedule's prompt
- **GovernanceHandler** — reviews proposed memory writes; approves or rejects
- **KnowledgeFlushHandler** — periodically distils conversation history into long-term facts

### Scheduler (`agent/scheduler.py`)

Polls `store.schedules` for due entries. Fires `ScheduleEvent` on the bus. Supports cron expressions (parsed by `agent/cron.py`) and one-shot `fire_at` timestamps.

## Shutdown

SIGTERM → `shutdown_event.set()` → `_shutdown_watcher` raises `_ShutdownRequested` → TaskGroup exits via `except*` → `finally` clears any pending asyncio cancellations → `mcp.disconnect_all()` + `store.close()`.

The explicit `while task.cancelling(): task.uncancel()` loop before teardown prevents anyio cancel scope errors during `disconnect_all()`.

## Configuration

| File | Purpose |
|------|---------|
| `.env` | Secrets and environment-specific settings (never committed) |
| `config/mcp_servers.json` | MCP server definitions; `${VAR}` refs expand from `.env` |
| `profile/PERSONALITY.md` | Agent persona |
| `profile/PROTOCOLS.md` | Behavioural rules |
| `profile/USER.md` | Information about the user |
| `profile/CHECKIN.md` | Instructions for proactive check-ins |
