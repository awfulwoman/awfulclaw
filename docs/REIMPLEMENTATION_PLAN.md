# Reimplementation Plan

This document describes a clean-room reimplementation of awfulclaw in Python, informed by the limitations documented in `ARCHITECTURE.md`. The goal is a significantly more elegant, extensible, and correct system while preserving everything that works well (MCP tooling, the connector abstraction, the memory model, cron scheduling).

## Goals

- **Separation of concerns** — no more 437-line monolith loop; each responsibility lives in its own module with a clear interface
- **Structured data end-to-end** — typed message objects, JSON-lines conversation storage, no regex parsing of markdown files
- **Unified storage** — single SQLite database for all persistent state; markdown files only for human-editable config (PERSONALITY.md, USER.md)
- **Reliable Claude invocation** — `claude` CLI subprocess, structured JSON output, retry logic
- **Relevance-aware context** — ranked context assembly, semantic search via `sqlite-vec`
- **Composable event pipeline** — middleware stack replaces baked-in interceptors; new behaviours added without touching core

## Package Layout

The package uses subdirectories to group files by role. Each directory is a Python package with an `__init__.py` that exports its public interface.

No file carries sensitivity headers or classification metadata — immutability is enforced at the mount level. See `PHILOSOPHY.md` for the full model.

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
    __init__.py
    rate_limit.py
    secret.py
    location.py
    slash.py
    typing.py
    agent.py           # AgentMiddleware (terminal middleware)
  handlers/
    README.md          # What handlers are, difference from middleware, how to add one
    __init__.py
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
4. **CLI over SDK.** Auth comes from a Claude subscription via OAuth, not an API key — the Anthropic Python SDK is not used. The `claude` CLI handles OAuth transparently. Improvements over the current implementation come from a persistent session, structured `stream-json` output, and retry logic around the subprocess — not from switching auth models.
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
    SDK[Anthropic SDK\nclaude-3-x]
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
    Agent -->|messages + tools| SDK
    SDK -->|tool calls| MCP
    MCP -->|tool results| SDK
    SDK -->|reply| Agent
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

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
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

    async def list_open_tasks() -> list[Task]
    async def upsert_task(Task)

    async def kv_get(key) -> str | None
    async def kv_set(key, value)
```

**Differs from original:** No JSON file for schedules, no regex-parsed markdown for conversations, no split between `memory.py` and `db.py`. One module, one file, one schema.

---

### Vector Index (`store.py`, via `sqlite-vec`)

**Responsibility:** Semantic search over facts and people for context assembly.

**Design:** `sqlite-vec` extension loaded at connection time. Embeddings generated via Anthropic's `text-embedding-3-small` (or locally via `sentence-transformers` — configurable). Embeddings stored as BLOB in the same row as the content. Search uses cosine similarity.

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
6. `middleware/agent.py` — invokes the agent; attaches reply to event

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

**Responsibility:** Invoke Claude via the `claude` CLI; manage a persistent session, handle retries, and parse structured output.

**Authentication:** This app uses a Claude subscription (OAuth), not an API key. The Anthropic Python SDK is not used — it requires API key auth. The `claude` CLI binary handles OAuth transparently, storing and refreshing tokens in `~/.claude/`. This directory is mounted as a named volume in the container so tokens survive across rebuilds.

**Design:** Spawns a persistent `claude` subprocess with `--output-format stream-json` for structured output. The session is reused across turns — avoiding per-turn startup cost — and respawned automatically if it dies or times out. MCP servers are attached via `--mcp-config` as today. Exponential backoff on non-zero exit codes.

```python
class ClaudeClient:
    async def complete(
        self,
        messages: list[Turn],
        system: str,
        mcp_config: Path,
    ) -> str: ...
```

The `stream-json` output format emits newline-delimited JSON events (text deltas, tool use, stop reason), replacing the fragile sentinel-marker approach in the current implementation. Tool-use round-trips are handled within the persistent session — Claude calls a tool, the MCP server responds, Claude continues — without restarting the process.

**Differs from original:** Persistent session (not fresh subprocess per turn). Structured `stream-json` output (not stdout scraping with sentinel markers). Retry logic. Same CLI-based auth model — OAuth subscription, no API key required.

**Container note:** The `claude` binary is installed in the Docker image at build time. The `~/.claude/` auth directory is a named volume, writable, never committed to the repo.

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
        AgentMiddleware(agent),
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

The app is a **coordination layer**, not a data store. External systems are the canonical source of truth for their respective domains.

**Long-term storage must use open, widely-supported formats.** Markdown for text. CSV for tabular data. Standard image formats (JPEG, PNG, etc.) for images. Open protocols (IMAP, CalDAV) for services. Data should never be locked inside an application or a proprietary format — it should be readable by any text editor, transferable to any tool, and survivable beyond the lifetime of this app.

SQLite is acceptable for working state precisely because it is not long-term storage. Anything that matters long-term lives in flat files.

| Domain | Canonical source |
|--------|-----------------|
| Long-form notes and knowledge | Obsidian |
| Events and scheduling | Google Calendar |
| Tasks and to-dos | Obsidian or a dedicated task manager |
| Email | IMAP |
| Contacts | People profiles (MCP tool) |

The agent reads from and writes to these systems via MCP. It does not replace them.

### SQLite as working memory

The local SQLite database is a **hot cache** — fast, structured storage that the agent can query during context assembly without making external API calls on every turn. It holds:

- **Facts** — things the agent has learned about the user and their world (preferences, context, state)
- **People** — contact profiles and relationship context
- **Conversation history** — recent turns for in-context recall
- **Coordination state** — poll offsets, pending secrets, schedule timing

This data is ephemeral in the sense that it serves the agent's immediate reasoning. It is not the user's authoritative record of anything.

### Obsidian as long-term knowledge store

Facts and people profiles are written out to Obsidian daily via `handlers/knowledge_flush.py`. This gives the user a human-readable, searchable, permanent record of everything the agent has learned — living alongside their own notes in Obsidian rather than locked inside the app's database.

The daily flush writes:
- One note per person in `Contacts/` (updated in place)
- A rolling `Agent Knowledge/facts.md` updated with current facts
- A daily conversation summary to `Agent Logs/YYYY-MM-DD.md`

On first run or after a database reset, the agent can rebuild its working knowledge by reading these Obsidian notes back in.

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

These live in `AGENT_CONFIG_PATH` on the host, mounted read-only into the container. The agent reads them; it cannot write to them. The user edits them directly on the host.

---

## Implementation Phases

### Phase 1: Core scaffolding
- `Settings` via pydantic-settings
- `Store` with full schema and async API
- `ClaudeClient` with SDK, tool-use loop, retry
- `MCPClient` with persistent connections
- Smoke test: single-turn invoke from a script

### Phase 2: Connectors and bus
- `bus.py` with typed events
- `connectors/telegram.py` (async, offset in store.kv)
- `connectors/tui.py` (Textual-based, for local dev without Telegram)
- Basic `pipeline.py` with `middleware/agent.py` only
- End-to-end: receive message → Claude reply → send (works with both connectors)

### Phase 3: Context and memory
- `context.py` (`ContextAssembler`) with budget-based ranking
- `sqlite-vec` embedding + semantic search
- Full system prompt with SOUL, USER, facts, people, tasks, schedules

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
- PERSONALITY.md, PROTOCOLS.md, and USER.md copied into `AGENT_CONFIG_PATH` on the host
- facts/people DB migrated via SQL

---

## Containerisation

### Principles

- Every service runs as a **non-root user**. Docker's default of running as root is not acceptable. The core agent and every MCP server container specifies a named non-root user (`agent`, UID 1000) via the `USER` Dockerfile directive.
- **All Linux capabilities dropped.** `cap_drop: ALL` in compose.yaml. No capabilities are added back — this app needs none.
- **`no-new-privileges`** — processes inside containers cannot escalate privileges even if a vulnerability exists.
- **Read-only root filesystem** on the core agent container. Everything writable is an explicit bind mount. Code immutability is physically enforced — `handlers/governance.py` cannot be modified by any running process, including the agent itself.

### Service layout

External MCP servers (IMAP, Google Calendar, GitHub, Home Assistant) each run as their own container — separate credentials, separate network access, separate failure domains. The memory MCP server is different: it accesses only the local SQLite DB, has no external network access, and is so tightly coupled to the agent that separating it adds process-boundary overhead with no isolation benefit. It runs as a local stdio process spawned by the agent, registered in `config/mcp_servers.json` exactly as today — not a compose service.

All mutable state uses **bind mounts** (explicit host paths) rather than named volumes. Bind mounts are transparent — the host directory is visible, easily backed up with any standard tool (rsync, Time Machine, restic), and the path is unambiguous.

**File permissions:** The container runs as UID/GID 1000. The host directories must be owned by the same UID, or the container will fail to write. Create them explicitly before first run:

```bash
# Run once on the host before starting containers
mkdir -p ${MEMORY_PATH} ${AGENT_CONFIG_PATH} ${CLAUDE_AUTH_PATH}
chown -R 1000:1000 ${MEMORY_PATH} ${CLAUDE_AUTH_PATH}
# AGENT_CONFIG_PATH is read-only in the container — owned by the host user, not 1000
```

If the host user's UID differs from 1000, set `user: "${UID}:${GID}"` in compose and pass those values via `.env` or shell export. Avoid running as root — this negates the security benefit.

```yaml
# compose.yaml (outline)
services:
  agent:
    image: ghcr.io/owner/agent:latest
    user: "1000:1000"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    tmpfs: [/tmp]
    volumes:
      - ${MEMORY_PATH}:/app/memory                    # read-write working state
      - ${AGENT_CONFIG_PATH}:/app/agent_config:ro     # PERSONALITY.md, PROTOCOLS.md, USER.md
      - ./config:/app/config:ro                       # mcp_servers.json (in repo)
      - ${CLAUDE_AUTH_PATH}:/home/agent/.claude         # OAuth token, writable for refresh
    env_file: .env                                    # injected at runtime, never in image
    restart: unless-stopped

  mcp-imap:
    image: ghcr.io/owner/mcp-imap:latest
    user: "1000:1000"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    env_file: .env
    profiles: [imap]   # only started if IMAP is configured

  # mcp-gcal, mcp-github, mcp-homeassistant etc. follow the same pattern
  # Third-party MCP servers are added here as new services via PR
```

No `volumes:` top-level block — bind mounts need none. All paths are set in `.env` (gitignored), e.g.:

```
MEMORY_PATH=/home/charlie/awfulclaw-memory
AGENT_CONFIG_PATH=/home/charlie/awfulclaw-config
CLAUDE_AUTH_PATH=/home/charlie/.claude
```

### What lives in the repo vs. outside it

The repo is public. Nothing personal or secret ever touches it.

| Location | Contents |
|----------|----------|
| **Repo** | Application code, `compose.yaml`, `config/mcp_servers.json` template, `Dockerfile`s, GitHub Actions workflows |
| **`MEMORY_PATH` (read-write bind mount)** | SQLite DB, conversation history, facts, schedules. Back this up. |
| **`AGENT_CONFIG_PATH` (read-only bind mount)** | `PERSONALITY.md`, `PROTOCOLS.md`, `USER.md` — human-authored config, not writable by the container. Back this up. |
| **`.env` file** (gitignored) | Runtime secrets — Telegram token, IMAP credentials, API keys. Also sets `MEMORY_PATH`, `AGENT_CONFIG_PATH`, `CLAUDE_AUTH_PATH`. |
| **`CLAUDE_AUTH_PATH` (read-write bind mount)** | `~/.claude/` — OAuth token, writable for refresh; never in repo. |
| **GitHub Actions secrets** | `GHCR_TOKEN` for pushing images — no host credentials needed |

### CI/CD and graceful redeploy

Deploys are handled by **Watchtower**, which polls GHCR for image digest changes and restarts containers automatically. No inbound ports, no SSH, no webhook listener — GitHub Actions just builds and pushes; the host takes care of the rest.

```
PR merged to main
  → GitHub Actions builds images, pushes to GHCR
  → Watchtower detects digest change on next poll
  → Watchtower pulls new image, sends SIGTERM to running container
  → agent: finishes in-flight message, writes pending state to DB, exits
  → new container starts, resumes from bind-mount state (Telegram offset, DB intact)
```

Watchtower runs as part of the same compose project:

```yaml
  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - WATCHTOWER_POLL_INTERVAL=300        # check every 5 minutes
      - WATCHTOWER_CLEANUP=true             # remove old images after update
      - WATCHTOWER_SCOPE=awfulclaw          # only watch containers in this project
    restart: unless-stopped
```

Label containers that Watchtower should manage:

```yaml
  agent:
    ...
    labels:
      - com.centurylinklabs.watchtower.scope=awfulclaw
```

The agent handles `SIGTERM` gracefully — no new Claude invocations are started after the signal, the current one completes, and the process exits cleanly. `stop_grace_period: 30s` in compose.yaml gives it a window. No messages are dropped; the Telegram offset in the `kv` table ensures the new container resumes exactly where the old one left off.

Adding a new MCP server means adding a service to `compose.yaml` via PR. The agent proposes the diff; a human approves; CI pushes the new image; Watchtower deploys it. The agent never runs `docker` commands directly.

### Multi-architecture support

The agent runs on `linux/amd64` (standard Intel/AMD server) and `linux/arm64` (Raspberry Pi 4/5, Apple Silicon). Older 32-bit Pi models are not supported — Node.js (required by the `claude` CLI) dropped `linux/arm/v7` support.

GitHub Actions builds a multi-arch manifest with a single tag. Watchtower and Docker pull the correct layer automatically:

```yaml
# .github/workflows/build.yaml (relevant step)
- name: Build and push
  uses: docker/build-push-action@v5
  with:
    platforms: linux/amd64,linux/arm64
    push: true
    tags: ghcr.io/owner/agent:latest
```

QEMU emulation (`docker/setup-qemu-action`) handles cross-compilation in Actions without needing native ARM runners. Build times are longer but images are identical in behaviour.

**Raspberry Pi notes:**
- Use a 64-bit OS (Raspberry Pi OS Lite 64-bit or Ubuntu Server arm64)
- Ensure `CLAUDE_AUTH_PATH` is pre-populated on the Pi before first run — the OAuth flow must be completed on a machine with a browser, then the `~/.claude/` directory copied across
- The Pi is a good always-on host: low power (~5W), no sleep, no automatic reboots

### Shared host hardening

When running alongside other containers on the same host, two extra measures apply.

**Docker socket proxy.** Watchtower needs the Docker socket, which grants effective root over the entire host. On a shared host, replace the direct socket mount with [`tecnativa/docker-socket-proxy`](https://github.com/Tecnativa/docker-socket-proxy), which exposes only the API endpoints Watchtower actually requires:

```yaml
  socket-proxy:
    image: tecnativa/docker-socket-proxy
    environment:
      - CONTAINERS=1   # allow container list/inspect
      - POST=1         # allow restart/pull
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - socket-proxy
    restart: unless-stopped

  watchtower:
    image: containrrr/watchtower
    environment:
      - DOCKER_HOST=tcp://socket-proxy:2375
      - WATCHTOWER_POLL_INTERVAL=300
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_SCOPE=awfulclaw
    networks:
      - socket-proxy
    restart: unless-stopped
```

Watchtower never touches the raw socket — the proxy enforces what it can and cannot do.

**Network isolation.** Define an explicit network so awfulclaw containers cannot reach neighbours on the default bridge:

```yaml
networks:
  awfulclaw:
    driver: bridge

services:
  agent:
    networks: [awfulclaw]
  mcp-imap:
    networks: [awfulclaw]
  # etc.
```

**Resource limits.** Prevent a stuck agent from starving other services:

```yaml
  agent:
    mem_limit: 512m
    cpus: "1.0"
```

**`.env` permissions.** On a shared host, tighten the env file so other users cannot read secrets:

```bash
chmod 600 .env
```

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
| `claude.py` | Discard | Replaced by SDK-based ClaudeClient |
| `memory.py` | Discard | Replaced by Store |
| `db.py` | Discard | Replaced by Store |
| `briefings.py` | Discard | Orientation briefing handled in `main.py` startup; daily briefing is user-configured via the schedule MCP tool |
