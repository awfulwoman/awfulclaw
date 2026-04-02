# Reimplementation Plan

This document describes a clean-room reimplementation of awfulclaw in Python, targeting a dedicated Mac Mini (Apple Silicon) as the runtime environment. The agent and all MCP servers run as native macOS processes, supervised by launchd. No Docker, no containers.

The goal is a significantly more elegant, extensible, and correct system while preserving everything that works well (MCP tooling, the connector abstraction, the memory model, cron scheduling). For data philosophy and design values, see `PHILOSOPHY.md`.

---

## Goals

- **Separation of concerns** — no more 437-line monolith loop; each responsibility lives in its own module with a clear interface
- **Structured data end-to-end** — typed message objects, JSON-lines conversation storage, no regex parsing of markdown files
- **Unified storage** — single SQLite database for all persistent state; markdown files only for human-editable config (PERSONALITY.md, USER.md)
- **Reliable Claude invocation** — `claude` CLI subprocess, structured JSON output, retry logic
- **Relevance-aware context** — ranked context assembly, semantic search via `sqlite-vec`
- **Composable event pipeline** — middleware stack replaces baked-in interceptors; new behaviours added without touching core

## Package Layout

The package uses subdirectories to group files by role. Each directory is a Python package with an `__init__.py` that exports its public interface.

No file carries sensitivity headers or classification metadata — immutability is enforced at the filesystem level (file permissions). See `PHILOSOPHY.md` for the full model.

```
agent/
  main.py              # entry point — wiring only
  agent.py             # Agent: context assembly + Claude invocation
  bus.py               # Event bus
  context.py           # ContextAssembler
  pipeline.py          # Pipeline + Middleware ABC
  scheduler.py         # Scheduler async task
  store.py             # Store: unified SQLite layer
  config.py            # Settings via pydantic-settings
  connectors/
    README.md          # What a Connector is, how to implement one, available connectors
    __init__.py        # Connector ABC, Message, InboundEvent, OutboundEvent
    telegram.py        # TelegramConnector
    tui.py             # TUIConnector (Textual)
  middleware/
    README.md          # What middleware is, execution order, how to add a new one
    __init__.py        # Middleware Protocol, Next type alias
    rate_limit.py      # Per-sender rate limiting
    secret.py          # Intercepts next message as a pending secret value
    location.py        # Detects [Location: lat, lon] tag; writes to store, strips from message
    slash.py           # Handles /schedules, /restart and other slash commands
    typing.py          # Sends typing indicator before passing through
    invoke.py          # InvokeMiddleware (terminal middleware — invokes the agent)
  handlers/
    README.md          # What handlers are, difference from middleware, how to add one
    __init__.py        # Handler ABC, handler registry
    schedule.py        # ScheduleHandler
    checkin.py         # CheckinHandler
    knowledge_flush.py # Daily flush of facts/people/summaries to Obsidian
    governance.py      # Invariant checks for all autonomous instruction writes (personality_log + schedule prompts)
  mcp/
    README.md          # What MCP servers are, how to add a new one, config/mcp_servers.json format
    __init__.py        # MCPClient
    memory.py          # memory_write + memory_search tools
    schedule.py        # schedule tools
    imap.py            # email tools
    gcal.py            # Google Calendar tools
    owntracks.py       # location tools
    env_manager.py     # env_set / env_keys tools
    skills.py          # skill_read tool
```

This makes every file's role unambiguous without needing filename prefixes — `connectors/telegram.py` is clearly a connector, `middleware/location.py` is clearly middleware.

## Design Principles

1. **Events flow through a pipeline, not a monolith.** Inbound messages enter a middleware chain. Each middleware can transform, intercept, or pass through. New behaviours are new middleware.
2. **One database, one schema.** All persistent state (facts, people, schedules, conversations, tasks) lives in a single SQLite file with a clear schema. Markdown files are config, not storage.
3. **Typed messages everywhere.** Use dataclasses or Pydantic models for every message, turn, and event. No plain dicts, no regex parsing.
4. **CLI over SDK.** Auth comes from a Claude subscription via OAuth, not an API key — the Anthropic Python SDK is not used. The `claude` CLI handles OAuth transparently. Improvements over the current implementation come from structured `stream-json` output and retry logic around the subprocess — not from switching auth models.
5. **Async throughout.** No `run_in_executor` wrappers. All I/O is natively async — `httpx.AsyncClient`, `aiosqlite`, async MCP.
6. **Dependency injection over globals.** Components receive their dependencies at construction. No module-level singletons, no import-time side effects.

## Proposed Architecture

```mermaid
flowchart TD
    User([User])
    Transport[Transport Layer\nConnector ABC]
    Bus[Event Bus]
    Pipeline[Message Pipeline\nmiddleware stack]
    Agent[Agent\ncontext + invoke]
    CLI[Claude CLI\nstream-json]
    MCP[MCP Client\ntool dispatch]
    Store[Store\naiosqlite]
    Vec[Vector Index\nsqlite-vec]
    Sched[Scheduler]
    Config[Config\npydantic-settings]

    User <-->|messages| Transport
    Transport -->|InboundEvent| Bus
    Bus --> Pipeline
    Pipeline -->|filtered turn| Agent
    Agent -->|system prompt| Store
    Agent -->|semantic search| Vec
    Agent -->|messages + tools| CLI
    CLI -->|tool calls| MCP
    MCP -->|tool results| CLI
    CLI -->|reply| Agent
    Agent -->|OutboundEvent| Bus
    Bus --> Transport
    Store <-->|read/write| MCP

    Sched -->|ScheduleEvent| Bus
    Config -.->|configures| Transport
    Config -.->|configures| Agent
    Config -.->|configures| Sched
```

The key change from the current design: **the loop no longer owns logic**. It only ticks. Everything else is an event flowing through the bus.

## Component Breakdown

### Config (`config.py`)

**Responsibility:** Load and validate all settings at startup; fail fast on missing required values.

**Design:** Use `pydantic-settings` with a single `Settings` model. Each feature block is a nested model (e.g. `TelegramSettings`, `ImapSettings`). Optional features have `None` as default — code checks `settings.imap is not None` rather than `os.getenv`.

```python
class Settings(BaseSettings):
    model: str = "claude-sonnet-4-6"
    governance_model: str = "claude-haiku-4-5-20251001"  # classification only — no need for full model
    telegram: TelegramSettings
    imap: ImapSettings | None = None
    gcal: GCalSettings | None = None
    owntracks: OwnTracksSettings | None = None
    poll_interval: int = 5
    idle_interval: int = 60
    checkin_interval: int = 86400  # seconds between ambient check-ins (default 24h)
```

**Differs from original:** No 10+ loose `get_*()` functions. One settings object passed through DI.

---

### Store (`store.py`)

**Responsibility:** All persistent state in one `aiosqlite` database. Clean async API; no raw SQL outside this module.

**Schema:**

```sql
-- human-readable identity and profile (still markdown files, but indexed)
-- structured data lives here:

CREATE TABLE facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    embedding BLOB,          -- sqlite-vec float32 vector
    updated_at TEXT NOT NULL
);

CREATE TABLE people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    content TEXT NOT NULL,
    embedding BLOB,
    updated_at TEXT NOT NULL
);

CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    role TEXT NOT NULL,       -- 'user' | 'assistant'
    content TEXT NOT NULL,    -- JSON: text or list of content blocks
    timestamp TEXT NOT NULL
);

CREATE TABLE schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    cron TEXT,
    fire_at TEXT,
    prompt TEXT NOT NULL,
    silent INTEGER NOT NULL DEFAULT 0,
    tz TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_run TEXT
);

CREATE TABLE kv (
    key TEXT PRIMARY KEY,    -- general-purpose key-value (telegram offset, etc.)
    value TEXT NOT NULL
);

CREATE TABLE personality_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT NOT NULL,     -- the adaptation (e.g. "user mentioned bereavement — soften tone")
    verdict TEXT NOT NULL,   -- 'approved' (silent) | 'rejected' (discarded) | 'escalated' (active + user notified)
    timestamp TEXT NOT NULL,
    expires_at TEXT          -- NULL = indefinite; set for temporary adaptations
);

-- governance also covers schedule prompt changes; the schedules table prompt column
-- is treated as a governed field — writes pass through handlers/governance.py
```

**Public API:**

```python
class Store:
    async def get_fact(key) -> str | None
    async def set_fact(key, value, embed=True)
    async def list_facts() -> list[Fact]
    async def search_facts(query, limit=10) -> list[Fact]      # semantic

    async def get_person(id_or_name) -> Person | None
    async def set_person(Person)
    async def search_people(query, limit=10) -> list[Person]   # semantic

    async def add_turn(channel, role, content)
    async def recent_turns(channel, limit=40) -> list[Turn]

    async def list_schedules() -> list[Schedule]
    async def upsert_schedule(Schedule)
    async def delete_schedule(id)

    async def kv_get(key) -> str | None
    async def kv_set(key, value)
```

**Differs from original:** No JSON file for schedules, no regex-parsed markdown for conversations, no split between `memory.py` and `db.py`. One module, one file, one schema.

---

### Vector Index (`store.py`, via `sqlite-vec`)

**Responsibility:** Semantic search over facts and people for context assembly.

**Design:** `sqlite-vec` extension loaded at connection time. Embeddings generated locally via `sentence-transformers` using `all-MiniLM-L6-v2` (~80MB model, runs well on M-series chip). No API calls required. Embeddings stored as BLOB in the same row as the content. Search uses cosine similarity.

```python
async def search_facts(query: str, limit: int = 10) -> list[Fact]:
    embedding = await embed(query)
    return await db.execute(
        "SELECT *, vec_distance_cosine(embedding, ?) AS score "
        "FROM facts ORDER BY score LIMIT ?",
        [embedding, limit]
    )
```

**Differs from original:** Substring `LIKE` search replaced with vector similarity. No more missed matches due to wording differences.

---

### Transport / Connector (`connectors/`)

**Responsibility:** Adapter between a messaging platform and the event bus.

**Design:** Keep the `Connector` ABC from the original — it's good. Make it fully async. Each connector runs its own async task (not a background thread).

```python
class Connector(ABC):
    @abstractmethod
    async def start(self, on_message: Callable[[InboundEvent], Awaitable[None]]) -> None: ...
    @abstractmethod
    async def send(self, to: str, message: OutboundMessage) -> None: ...
    @abstractmethod
    async def send_typing(self, to: str) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
```

Two connectors ship in the new implementation:

**`connectors/telegram.py`** — uses `httpx.AsyncClient` with long-polling. Offset stored in `store.kv`. No background threads. Supports text, images, and typing indicators.

**`connectors/tui.py`** — a local terminal UI for development, debugging, and offline use. Built on [Textual](https://github.com/Textualize/textual). Renders a chat-style interface in the terminal with a scrollable message history panel and an input box. Runs as an async Textual app inside its own task; sends `InboundEvent` on Enter and renders `OutboundEvent` messages as they arrive.

```python
class TUIConnector(Connector):
    """
    Terminal chat UI built with Textual.
    Useful for local dev and running the agent without Telegram.
    Start with: uv run python -m agent --connector tui
    """
    async def start(self, on_message):
        self._on_message = on_message
        await self._app.run_async()   # Textual takes over the terminal

    async def send(self, to, message):
        self._app.post_message(AgentReply(message.text))

    async def send_typing(self, to):
        self._app.post_message(TypingIndicator())
```

The TUI connector doubles as the primary development harness — no Telegram credentials needed to run and test the agent locally.

**Differs from original:** Async-native (no `threading.Thread`). Connector pushes events via callback rather than being polled by the gateway. Gateway eliminated — bus takes its place. Connector selected via `--connector telegram|tui` CLI flag (default: `telegram`).

---

### Event Bus (`bus.py`)

**Responsibility:** Decouple producers (connectors, scheduler) from consumers (pipeline, outbound router).

**Design:** Thin wrapper around `asyncio.Queue`. Typed events. Subscribers register for event types.

```python
@dataclass
class InboundEvent:
    channel: str
    message: Message

@dataclass
class OutboundEvent:
    channel: str
    to: str
    message: OutboundMessage

@dataclass
class ScheduleEvent:
    schedule: Schedule
```

**Differs from original:** Replaces the gateway's thread-safe queue. Makes the scheduler a first-class event producer rather than something polled inside the idle tick.

---

### Message Pipeline (`pipeline.py`, `middleware/`)

**Responsibility:** Process inbound events through a middleware stack before they reach the agent.

**Design:** Classic middleware chain. Each middleware receives the event and a `next` callable. Can short-circuit (intercept) or pass through.

```python
class Middleware(Protocol):
    async def __call__(self, event: InboundEvent, next: Next) -> None: ...
```

**Built-in middleware (in order):**
1. `middleware/rate_limit.py` — per-sender rate limiting
2. `middleware/secret.py` — watches for pending secret keys; intercepts the next message as the value
3. `middleware/location.py` — detects `[Location: lat, lon]` format; writes to store; strips the tag from the message and passes the remainder through (stops chain only if the message was nothing but the tag)
4. `middleware/slash.py` — handles `/schedules`, `/restart`; stops chain
5. `middleware/typing.py` — sends typing indicator before passing through
6. `middleware/invoke.py` — invokes the agent; attaches reply to event

New behaviours (e.g. a `/remind` command) are a new file in `middleware/` — `pipeline.py` and `main.py` are never touched.

**Differs from original:** Interceptors extracted from `loop.py`. No shared mutable closure state between interceptors.

---

### Agent (`agent.py`)

**Responsibility:** Build context and invoke Claude; return a reply.

**Design:** Two sub-components: `ContextAssembler` and `ClaudeClient`.

```python
class Agent:
    async def reply(self, turn: Turn, channel: str) -> str: ...
    async def invoke(self, prompt: str, history: list[Turn] = []) -> str: ...
```

**Differs from original:** `reply()` is the main path (message → response); `invoke()` is used by the scheduler for prompt-driven turns. Both go through the same `ClaudeClient`.

---

### Context Assembler (`context.py`)

**Responsibility:** Build the system prompt from available memory, ranked by relevance.

**Design:**

1. Always-included sections (no size budget): identity, current time, SOUL, capabilities, USER profile
2. Budget-allocated sections (fill remaining space by relevance score):
   - Facts: scored by semantic similarity to incoming message + recency
   - People: scored by name mention + semantic similarity
   - Tasks: scored by recency
   - Schedules: always included (small, bounded)
3. Total budget: `model_context_limit - estimated_history_tokens - 2000` (not a fixed 8000)

```python
class ContextAssembler:
    async def build(self, message: str, sender: str | None, channel: str) -> str: ...
```

**Differs from original:** Relevance scoring replaces crude "drop oldest facts" truncation. Budget scales with actual conversation length rather than a fixed cap.

---

### Claude Client (`claude_client.py`)

**Responsibility:** Invoke Claude via the `claude` CLI; handle retries and parse structured output.

**Authentication:** This app uses a Claude subscription (OAuth), not an API key. The Anthropic Python SDK is not used — it requires API key auth. The `claude` CLI binary handles OAuth transparently, storing and refreshing tokens in `~/.claude/`.

**Design:** One-shot invocation per turn: `claude --print --output-format stream-json`. The agent manages conversation history via the Store and passes it as context each turn. MCP servers are attached via `--mcp-config` as today. Exponential backoff on non-zero exit codes.

```python
class ClaudeClient:
    async def complete(
        self,
        messages: list[Turn],
        system: str,
        mcp_config: Path,
    ) -> str: ...
```

The `stream-json` output format emits newline-delimited JSON events (text deltas, tool use, stop reason), replacing the fragile sentinel-marker approach in the current implementation.

**Differs from original:** Structured `stream-json` output (not stdout scraping with sentinel markers). Retry logic. Same CLI-based auth model — OAuth subscription, no API key required.

---

### MCP Client (`mcp_client.py`)

**Responsibility:** Manage MCP server connections and dispatch tool calls.

**Design:** Uses the official `mcp` Python SDK's client. Servers defined in `config/mcp_servers.json` (same format as today). Each server connected at startup as a persistent process via `StdioServerParameters`. Tool catalogue fetched at connection time and passed to Claude as `tools=`.

```python
class MCPClient:
    async def connect_all(self, config_path: Path) -> None: ...
    async def list_tools(self) -> list[ToolParam]: ...
    async def call_tool(self, name: str, arguments: dict) -> ToolResult: ...
    async def reload_if_changed(self) -> bool: ...
```

**Differs from original:** No `--mcp-config` flag on subprocess. Persistent connections rather than re-spawning every turn. Tool catalogue is live and doesn't require config regeneration.

**Third-party server installation:** When the agent identifies a capability gap, it may propose installing a third-party MCP server. The flow mirrors the secret-request pattern — the agent names a specific server, explains what it does, and waits for explicit user confirmation. On approval, the server is registered in `config/mcp_servers.json` and picked up on the next reload. Servers are run via `npx -y` (npm) or `uvx` (Python) without a permanent install. The agent cannot install servers without user approval — see `PHILOSOPHY.md`.

---

### Scheduler (`scheduler.py`)

**Responsibility:** Fire due schedules by posting `ScheduleEvent` to the bus.

**Design:** Runs as an independent async task. Sleeps until the next due schedule, wakes, posts the event, sleeps again. No polling loop comparing timestamps every 60 seconds.

```python
class Scheduler:
    async def run(self, bus: Bus, store: Store) -> None:
        while True:
            schedules = await store.list_schedules()
            next_due = earliest_due(schedules)
            if next_due:
                sleep_until(next_due.fire_time)
                await bus.post(ScheduleEvent(next_due))
            else:
                await asyncio.sleep(60)
```

Schedule events are handled by `handlers/schedule.py` (not in the message pipeline) which invokes `agent.invoke(schedule.prompt)` and optionally posts the reply as an `OutboundEvent`. Periodic ambient check-ins are handled by `handlers/checkin.py` — distinct from schedules, which fire blindly at a set time. The check-in reads `agent_config/CHECKIN.md` (a short patrol checklist maintained by the user), invokes Claude, and sends a reply only if Claude determines something warrants attention. If nothing does, it stays silent. `checkin_interval` in Settings controls frequency.

**Differs from original:** Scheduler is event-driven, not polled. No coupling to the idle tick. Schedule storage in SQLite (consistent with everything else).

---

### Core Loop (`main.py`)

**Responsibility:** Wire everything together and run. Nothing else.

```python
async def main():
    settings = Settings()
    store = await Store.connect(settings.db_path)
    bus = Bus()
    mcp = MCPClient()
    await mcp.connect_all(settings.mcp_config)
    claude = ClaudeClient(settings.model, mcp)
    assembler = ContextAssembler(store)
    agent = Agent(claude, assembler, store)

    pipeline = Pipeline([
        RateLimitMiddleware(),
        SecretCaptureMiddleware(store),
        LocationMiddleware(store),
        SlashCommandMiddleware(store),
        TypingMiddleware(),
        InvokeMiddleware(agent),
    ])

    connector = TelegramConnector(settings.telegram, store)
    scheduler = Scheduler()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(connector.start(bus.post))
        tg.create_task(scheduler.run(bus, store))
        tg.create_task(bus.run(pipeline, connector))
        tg.create_task(mcp.watch_config(settings.mcp_config))
```

**Differs from original:** `main.py` is ~30 lines of wiring, not 437 lines of logic.

---

## Data Philosophy

See `PHILOSOPHY.md` for the full data philosophy. In brief: the agent is a coordination layer, not a data store. SQLite is working memory; Obsidian is the long-term knowledge store. Facts and people are flushed daily to Obsidian via `handlers/knowledge_flush.py`.

## Memory and Storage Redesign

| Current | New |
|---------|-----|
| `memory/schedules.json` | `schedules` table in SQLite |
| `memory/conversations/YYYY-MM-DD.md` | `conversations` table in SQLite + daily summary flushed to Obsidian |
| `memory/tasks/*.md` | Removed — tasks live in the user's task manager, read via MCP |
| `memory/awfulclaw.db` facts/people | Same tables, same file, extended with embeddings; flushed daily to Obsidian |
| Regex parsing of markdown | Typed `Turn` objects, JSON content field |
| `.telegram_offset` file | `kv` table |

**What stays as markdown files** (human-edited config, not program state):
- `agent_config/PERSONALITY.md` — identity, personality, tone, values (*who the agent is*)
- `agent_config/PROTOCOLS.md` — operating rules, priorities, procedures (*how the agent behaves*)
- `agent_config/USER.md` — user profile
- `agent_config/CHECKIN.md` — ambient check-in checklist; short, human-maintained patrol prompt

These live in `agent_config/` on the Mac Mini, chmod 444. The agent reads them; it cannot write to them. The user edits them directly.

---

## Implementation Phases

### Phase 1: Core scaffolding
- `Settings` via pydantic-settings
- `Store` with full schema and async API
- `ClaudeClient` with CLI subprocess, `stream-json` parsing, retry
- `MCPClient` with persistent connections
- Smoke test: single-turn invoke from a script

### Phase 2: Connectors and bus
- `bus.py` with typed events
- `connectors/telegram.py` (async, offset in store.kv)
- `connectors/tui.py` (Textual-based, for local dev without Telegram)
- Basic `pipeline.py` with `InvokeMiddleware` only
- End-to-end: receive message → Claude reply → send (works with both connectors)

### Phase 3: Context and memory
- `context.py` (`ContextAssembler`) with budget-based ranking
- `sqlite-vec` embedding + semantic search
- Full system prompt with PERSONALITY, PROTOCOLS, USER, facts, people, schedules

### Phase 4: Middleware
- `middleware/secret.py`
- `middleware/location.py`
- `middleware/slash.py`
- `middleware/rate_limit.py`
- `middleware/typing.py`

### Phase 5: Scheduler
- `schedules` table + cron evaluation
- `scheduler.py` async task
- `handlers/schedule.py`
- `handlers/knowledge_flush.py` — daily Obsidian export of facts, people, conversation summary

### Phase 6: Idle and check-in
- `handlers/checkin.py` — reads `CHECKIN.md`, invokes Claude, sends only if warranted
- `checkin_interval` cooldown via `kv` table (last fired timestamp)

### Phase 7: Feature parity
- Location/timezone updates (OwnTracks)
- Email triage
- MCP config hot-reload
- `/restart` slash command
- Orientation briefing — on first startup, the agent sends a brief message summarising its current state (known schedules, recent context, available tools) so it can pick up coherently rather than starting cold

### Phase 8: Migration
- Import script: read `schedules.json` → insert into new DB
- Import script: read `conversations/YYYY-MM-DD.md` → insert turns into new DB
- PERSONALITY.md, PROTOCOLS.md, USER.md, and CHECKIN.md copied into `agent_config/`
- facts/people DB migrated via SQL

---

## Service Management

The agent runs natively on a dedicated Mac Mini (Apple Silicon). No Docker, no containers. Process supervision, logging, and restart are handled by macOS launchd.

### launchd services

Two launchd plists manage the system:

**`ai.awfulclaw.agent`** — the agent process itself.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.awfulclaw.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/uv</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>agent</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/awfulclaw</string>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/usr/local/var/log/awfulclaw/agent.log</string>
    <key>StandardErrorPath</key>
    <string>/usr/local/var/log/awfulclaw/agent.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

Environment variables are loaded from `.env` by the agent at startup (via `pydantic-settings`), not injected by launchd. This keeps secrets out of the plist.

**`ai.awfulclaw.watcher`** — monitors `app/` for changed `.py` files on the `main` branch and restarts the agent with a 60s debounce. Already exists in `scripts/`.

### File permissions

On a single-purpose Mac Mini, file permissions provide config immutability without containers or sandboxing:

```bash
# Run once during initial setup
chmod -R 444 agent_config/      # PERSONALITY.md, PROTOCOLS.md, USER.md, CHECKIN.md — read-only
chmod 600 .env                  # secrets — readable only by the host user
# memory/ is writable by default — no special permissions needed
```

Code files are owned by the host user. The agent process runs as the same user but the governance layer (`handlers/governance.py`) and middleware are protected by being part of the git-managed codebase — changes require a PR, human approval, and merge to `main`.

### MCP servers

All MCP servers run as **stdio child processes** of the agent. No separate services, no SSE bridges. The agent spawns them according to `config/mcp_servers.json` and communicates via stdin/stdout. This is the simplest and most reliable approach — it works because everything runs on the same machine.

### Deployment

Deploys use a simple git-based flow with no inbound ports, no CI/CD pipeline, and no image registry:

```
PR merged to main
  → launchd periodic job runs `git pull origin main` (every 5 minutes)
  → file watcher (ai.awfulclaw.watcher) detects changed .py files
  → 60s debounce
  → watcher sends SIGTERM to agent, launchd restarts it automatically
  → new code is live; Telegram offset in kv table ensures no messages dropped
```

### Graceful shutdown

The agent handles `SIGTERM`: no new Claude invocations are started after the signal, the current one completes, pending state is written to DB, and the process exits cleanly. launchd restarts it automatically via `KeepAlive`. No messages are dropped — the Telegram offset in the `kv` table ensures the new process resumes exactly where the old one left off.

### What lives in the repo vs. outside it

The repo is public. Nothing personal or secret ever touches it.

| Location | Contents |
|----------|----------|
| **Repo** | Application code, `config/mcp_servers.json`, `config/skills/*.md`, launchd plists, scripts |
| **`agent_config/`** (read-only via chmod) | `PERSONALITY.md`, `PROTOCOLS.md`, `USER.md`, `CHECKIN.md` — human-authored config. Back this up. |
| **`memory/`** (read-write) | SQLite DB, conversation history, facts, schedules. Back this up. |
| **`.env`** (gitignored, chmod 600) | Runtime secrets — Telegram token, IMAP credentials, API keys. |
| **`~/.claude/`** | OAuth tokens for the `claude` CLI. Writable for token refresh; never in repo. |

### Backups

All mutable state lives in two places: `memory/` (SQLite DB) and `agent_config/` (markdown config). Both are plain files on disk, easily backed up with Time Machine, rsync, or restic. No volume mounts, no container filesystems to extract from.

## What to Reuse

| Component | Verdict | Notes |
|-----------|---------|-------|
| `connector.py` Connector ABC | Reuse, adapt | Make async; becomes `connectors/__init__.py` |
| `telegram.py` | Reuse, adapt | Move to `connectors/telegram.py`; replace `requests` with `httpx.AsyncClient` |
| `scheduler.py` cron logic | Reuse | Extract `get_due` / `should_wake` into `scheduler.py` |
| `context.py` prompt sections | Reuse text | Replace assembly logic; keep in `context.py` |
| MCP server implementations | Reuse, move | Move into `mcp/` subdirectory (`mcp/imap.py`, `mcp/gcal.py`, etc.) |
| `config/mcp_servers.json` | Reuse as-is | Format unchanged |
| `memory/PERSONALITY.md`, `USER.md` | Reuse as-is | Move to `AGENT_CONFIG_PATH` on host |
| `env_utils.py` | Reuse as-is | |
| `location.py` | Reuse as-is | |
| `loop.py` | Discard | Logic extracted into pipeline middleware |
| `gateway.py` | Discard | Replaced by bus + async connectors |
| `claude.py` | Discard | Replaced by `ClaudeClient` with `stream-json` output parsing |
| `memory.py` | Discard | Replaced by Store |
| `db.py` | Discard | Replaced by Store |
| `briefings.py` | Discard | Orientation briefing handled in `main.py` startup; daily briefing is user-configured via the schedule MCP tool |
