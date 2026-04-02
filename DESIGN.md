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

No file carries sensitivity headers or classification metadata — immutability is enforced at the tool level (no MCP tool exposes file-write outside `memory/`), with filesystem permissions as defence in depth. See `PHILOSOPHY.md` for the full model.

```
agent/
  main.py              # entry point — wiring only
  agent.py             # Agent: context assembly + Claude invocation
  bus.py               # Event bus
  context.py           # ContextAssembler
  pipeline.py          # Pipeline + Middleware ABC
  scheduler.py         # Scheduler async task
  store.py             # Store: unified SQLite layer
  claude_client.py     # ClaudeClient: CLI subprocess, stream-json parsing, retry
  config.py            # Settings via pydantic-settings
  connectors/
    README.md          # What a Connector is, how to implement one, available connectors
    __init__.py        # Connector ABC, Message, InboundEvent, OutboundEvent
    telegram.py        # TelegramConnector
    rest.py            # RESTConnector (HTTP API + SSE streaming)
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
    governance.py      # Invariant checks for autonomous instruction writes (personality_log + schedule prompts)
  mcp/
    README.md          # What MCP servers are, how to add a new one, config/mcp_servers.json format
    __init__.py        # MCPClient
    memory.py          # memory_write + memory_search tools
    schedule.py        # schedule tools
    imap.py            # email tools
    eventkit.py        # calendar + reminders tools (macOS EventKit via pyobjc)
    contacts.py        # contacts tools (macOS Contacts via pyobjc)
    weather.py         # weather tools (Open-Meteo, no auth)
    owntracks.py       # location tools
    env_manager.py     # env_set / env_keys tools
    skills.py          # skill_read tool
```

This makes every file's role unambiguous without needing filename prefixes — `connectors/telegram.py` is clearly a connector, `middleware/location.py` is clearly middleware.

## Design Principles

1. **Events flow through a pipeline, not a monolith.** Inbound messages enter a middleware chain. Each middleware can transform, intercept, or pass through. New behaviours are new middleware.
2. **One database, one schema.** All persistent state (facts, people, schedules, conversations) lives in a single SQLite file with a clear schema. Markdown files are config, not storage.
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
    model_config = SettingsConfigDict(env_prefix="AWFULCLAW_")
    model: str = "claude-sonnet-4-6"
    governance_model: str = "claude-haiku-4-5-20251001"  # classification only — no need for full model
    memory_path: Path = Path("memory")                   # SQLite DB, working state
    agent_config_path: Path = Path("agent_config")       # PERSONALITY.md, PROTOCOLS.md, USER.md, CHECKIN.md
    telegram: TelegramSettings
    imap: ImapSettings | None = None
    eventkit: EventKitSettings | None = None
    contacts: ContactsSettings | None = None
    owntracks: OwnTracksSettings | None = None
    poll_interval: int = 5
    idle_interval: int = 60
    checkin_interval: int = 86400  # seconds between ambient check-ins (default 24h)
```

Paths default to directories relative to the working directory but can be overridden via environment variables (`MEMORY_PATH`, `AGENT_CONFIG_PATH`). This allows mounting mutable state on a separate filesystem — e.g. a ZFS dataset with snapshots and replication — while keeping the code checkout on the boot volume.

**Rationale:** One settings object passed through DI eliminates scattered `get_*()` functions and makes configuration testable.

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

**Rationale:** All persistent state in one module with one schema. No format translation between storage and application — typed objects go in, typed objects come out.

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

**Rationale:** Vector similarity finds semantically related content regardless of exact wording — "feeling down" matches a query for "sad".

---

### Transport / Connector (`connectors/`)

**Responsibility:** Adapter between a messaging platform and the event bus.

**Design:** The `Connector` ABC defines a clean boundary between transport and application logic. Fully async — each connector runs its own async task, no threads.

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

**`connectors/rest.py`** — an HTTP API for programmatic access. Built on an async ASGI framework (e.g. Starlette or FastAPI). Exposes a minimal chat endpoint that accepts a message and returns the agent's reply. Useful for integrating with mobile apps, web dashboards, webhooks, or any client that speaks HTTP.

```python
class RESTConnector(Connector):
    """
    HTTP API connector.
    Start with: uv run python -m agent --connector rest
    Listens on port 8080 by default (configurable via REST_PORT).
    """
    async def start(self, on_message):
        self._on_message = on_message
        await self._server.serve()     # uvicorn ASGI server

    async def send(self, to, message):
        self._pending_responses[to].set_result(message)

    async def send_typing(self, to):
        pass  # no-op for REST; could use SSE for streaming
```

The REST connector uses a request/response model: each inbound POST creates an `InboundEvent`, the pipeline processes it, and the reply is returned in the HTTP response. For longer interactions, Server-Sent Events (SSE) can stream partial replies and typing indicators.

```
POST /chat
  {"message": "What's on my calendar today?"}
  → 200 {"reply": "You have a dentist appointment at 2pm."}

GET /chat/stream  (SSE, optional)
  {"message": "Summarise my week"}
  → event: typing
  → event: delta  data: {"text": "This week you..."}
  → event: done   data: {"reply": "This week you had 3 meetings..."}
```

The REST API serves two purposes: **external clients** (terminal UIs, web apps, mobile apps) and — critically — **end-to-end testing**.

Without an API, testing the agent means sending real messages through Telegram and reading the replies by hand. This makes automated testing nearly impossible and slows development to a crawl. The REST connector solves this: a test can POST a message, receive the reply as JSON, and assert on the content — all in a normal `pytest` run, no Telegram account needed.

```python
# Example end-to-end test
async def test_schedule_creation(agent_client):
    resp = await agent_client.post("/chat", json={"message": "Remind me to call mum every Sunday at 10am"})
    assert resp.status_code == 200
    reply = resp.json()["reply"]
    assert "sunday" in reply.lower()

    # Verify the schedule was actually created
    resp = await agent_client.post("/chat", json={"message": "/schedules"})
    assert "call mum" in resp.json()["reply"].lower()
```

The test harness starts the agent with the REST connector and an in-memory SQLite database, giving full end-to-end coverage through the real middleware pipeline, context assembler, and Claude invocation — not mocked substitutes. This is the primary development and CI feedback loop.

Client implementations live outside this repo.

**Design notes:** Async-native — each connector runs its own async task, no threads. Connectors push events via callback rather than being polled. Connector selected via `--connector telegram|rest` CLI flag (default: `telegram`).

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

**Rationale:** Decouples producers from consumers. The scheduler is a first-class event producer on equal footing with connectors.

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

**Rationale:** Each middleware is an independent unit with no shared mutable state. New behaviours are new files — core modules are never touched.

---

### Agent (`agent.py`)

**Responsibility:** Build context and invoke Claude; return a reply.

**Design:** Two sub-components: `ContextAssembler` and `ClaudeClient`.

```python
class Agent:
    async def reply(self, turn: Turn, channel: str) -> str: ...
    async def invoke(self, prompt: str, history: list[Turn] = []) -> str: ...
```

**Design notes:** `reply()` is the main path (message → response); `invoke()` is used by the scheduler for prompt-driven turns. Both go through the same `ClaudeClient`.

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

**Rationale:** Budget scales with actual conversation length rather than a fixed cap. Relevance scoring ensures the most useful context is included first.

---

### Claude Client (`claude_client.py`)

**Responsibility:** Invoke Claude via the `claude` CLI; handle retries and parse structured output.

**Authentication:** This app uses a Claude subscription (OAuth), not an API key. The Anthropic Python SDK is not used — it requires API key auth. The `claude` CLI binary handles OAuth transparently, storing and refreshing tokens in `~/.claude/`.

**Design:** One-shot invocation per turn. The system prompt and conversation history are assembled into a single prompt string by `ContextAssembler` and passed to the CLI via `--print --output-format stream-json`. The prompt is provided via stdin (piped to the subprocess) to avoid argument length limits. MCP servers are attached via `--mcp-config`. Exponential backoff on non-zero exit codes.

The CLI does not manage multi-turn state — the agent replays relevant history each invocation as part of the assembled prompt. This is intentional: it keeps conversation management in the Store and gives the `ContextAssembler` full control over what context is included.

```python
class ClaudeClient:
    async def complete(
        self,
        prompt: str,         # assembled by ContextAssembler (system + history + current turn)
        mcp_config: Path,
    ) -> str: ...
```

The `stream-json` output format emits newline-delimited JSON events (text deltas, tool use, stop reason), replacing the fragile sentinel-marker approach in the current implementation.

**Design notes:** Prompt passed via stdin to avoid shell argument limits. Structured `stream-json` output for reliable parsing. Exponential backoff on failure. CLI-based auth — OAuth subscription, no API key required. The exact CLI flags should be verified against the installed `claude` version during Phase 1 implementation.

---

### MCP Client (`mcp/__init__.py`)

**Responsibility:** Manage MCP server connections and dispatch tool calls.

**Design:** Uses the official `mcp` Python SDK's client. Servers defined in `config/mcp_servers.json` (same format as today). Each server connected at startup as a persistent process via `StdioServerParameters`. Tool catalogue fetched at connection time and passed to Claude as `tools=`.

```python
class MCPClient:
    async def connect_all(self, config_path: Path) -> None: ...
    async def list_tools(self) -> list[ToolParam]: ...
    async def call_tool(self, name: str, arguments: dict) -> ToolResult: ...
    async def reload_if_changed(self) -> bool: ...
```

**Design notes:** Persistent connections to MCP servers — spawned once at startup, reused across turns. Tool catalogue is fetched live at connection time and refreshed on config reload.

**Third-party server installation:** When the agent identifies a capability gap, it may propose installing a third-party MCP server. The flow mirrors the secret-request pattern — the agent names a specific server, explains what it does, and waits for explicit user confirmation. On approval, the server is registered in `config/mcp_servers.json` and picked up on the next reload. Servers are run via `npx -y` (npm) or `uvx` (Python) without a permanent install. The agent cannot install servers without user approval — see `PHILOSOPHY.md`.

**Built-in CLI tools vs MCP tools:** The `claude` CLI provides several built-in tools (`WebSearch`, `WebFetch`, `Bash`, `Read`, `Edit`, etc.) that are available to Claude alongside MCP tools. Web search does not need an MCP server — the CLI's built-in `WebSearch` and `WebFetch` tools handle it. The PROTOCOLS.md capabilities section references these tools by name so Claude uses them rather than hallucinating tool calls (a problem in the legacy app, where the system prompt mentioned "web search" without anchoring it to a real tool name).

---

### Credential Manager (`mcp/env_manager.py`)

**Responsibility:** Allow the agent to request and store sensitive credentials without ever being able to read them back.

**Design:** An MCP server exposing two tools:

- `env_keys()` — lists the keys currently defined in `.env` (names only, not values)
- `env_set(key)` — registers a pending key name; the next user message is captured as the value by `SecretCaptureMiddleware`

The flow:

1. Agent identifies it needs a credential (e.g. `IMAP_PASSWORD`)
2. Agent calls `env_set("IMAP_PASSWORD")` — this registers the key as pending
3. Agent tells the user: "Please send me your IMAP password. The next message you send will be stored securely."
4. `SecretCaptureMiddleware` intercepts the user's next message as the value
5. `env_manager` appends `IMAP_PASSWORD=<value>` to `.env`
6. On next restart, the new env var is available to the relevant MCP server

**Security property:** Write-only from Claude's perspective. No `env_get` tool exists — Claude can store credentials but never read them back. The `.env` file is loaded by pydantic-settings at startup, so values are available to the Python process (which needs them to connect to Telegram, IMAP, etc.), but no MCP tool exposes secret values to Claude. This prevents credential exfiltration if a prompt injection attack is successful.

---

### Calendar & Reminders (`mcp/eventkit.py`)

**Responsibility:** Read/write access to macOS Calendar and Reminders via the EventKit framework, replacing the previous `gcal.py` design.

**Design:** Uses `pyobjc-framework-EventKit` to access the system `EKEventStore`. This gives the agent access to **all calendars and reminder lists synced to macOS** — iCloud, Google, Exchange, CalDAV — without any per-service API authentication. The user's existing Calendar.app sync handles auth.

**Dependencies:** `pyobjc-framework-EventKit` (v11.0+, Python ≥3.10)

**Tools exposed:**

```
calendar_list()         → list of calendars with source (iCloud, Google, etc.)
calendar_events(
    start, end,         # ISO 8601 date/time range
    calendar=None       # filter to specific calendar; None = all
) → list of events with title, start, end, location, notes, calendar name

calendar_create_event(
    title, start, end,
    calendar=None,      # target calendar; None = default
    location=None,
    notes=None
) → event ID

calendar_update_event(id, **fields) → updated event
calendar_delete_event(id) → confirmation

reminders_lists()       → list of reminder lists
reminders_incomplete(
    list=None,          # filter to specific list; None = all
    due_before=None     # only reminders due before this date
) → list of reminders with title, due date, priority, notes, list name

reminders_completed(
    list=None,
    completed_after=None
) → list of recently completed reminders

reminder_create(
    title,
    list=None,          # target list; None = default
    due=None,           # ISO 8601 date/time
    priority=None,      # 0 (none), 1 (high), 5 (medium), 9 (low)
    notes=None
) → reminder ID

reminder_complete(id)   → confirmation
reminder_update(id, **fields) → updated reminder
reminder_delete(id)     → confirmation
```

**Why EventKit instead of Google Calendar API:**

- **Zero auth complexity.** No OAuth client ID, no refresh tokens, no consent screens. The user's macOS account sync handles everything.
- **Multi-provider.** Works with Google Calendar, iCloud, Exchange, and any CalDAV provider — all unified through one API.
- **Reminders included.** Same framework covers Apple Reminders, which fills the "tasks live in the user's task manager, read via MCP" gap from the memory redesign.
- **Offline resilience.** EventKit caches locally; reads work even when the network is down.
- **Natural fit.** The agent runs on a dedicated Mac — leveraging the platform is the whole point.

**Design notes:** `EKEventStore` is thread-safe but not async. Calls are synchronous and fast (local SQLite under the hood), so `asyncio.to_thread()` wrapping is acceptable here — these are sub-millisecond local reads, not network I/O. Calendar write operations (create/update/delete) follow the draft-first protocol from PROTOCOLS.md — the agent presents the draft and waits for approval before committing.

**TCC permissions:** Requires `kTCCServiceCalendar` and `kTCCServiceReminders` grants. See the TCC setup section under Service Management.

---

### Contacts (`mcp/contacts.py`)

**Responsibility:** Read-only access to macOS Contacts via the Contacts framework.

**Design:** Uses `pyobjc-framework-Contacts` to query the system `CNContactStore`. Like EventKit, this accesses all synced contact sources (iCloud, Google, Exchange, CardDAV) without per-service auth.

**Dependencies:** `pyobjc-framework-Contacts` (Python ≥3.10, macOS ≥10.11)

**Tools exposed:**

```
contacts_search(
    query               # name, email, or phone number fragment
) → list of matching contacts with name, phone numbers, emails, organisation

contacts_get(id) → full contact details
```

**Design notes:** Read-only — the agent cannot create or modify contacts. This is intentional: contacts are a reference resource, not an agent workspace. The agent uses contacts to resolve ambiguous references ("text Charlie" → lookup phone number) and to enrich context ("meeting with Sarah" → pull org/role from contacts).

`CNContactStore` is synchronous; use `asyncio.to_thread()` as with EventKit.

**TCC permissions:** Requires `kTCCServiceContacts`. See the TCC setup section under Service Management.

---

### Weather (`mcp/weather.py`)

**Responsibility:** Current conditions and forecast data for the user's location.

**Design:** Uses the [Open-Meteo API](https://open-meteo.com/) — free, no API key, no signup, no rate limits for fair use. Location is pulled from the user's last known coordinates in `store.kv` (set by `middleware/location.py` via OwnTracks). Falls back to the timezone in USER.md if no location is available.

**Dependencies:** `httpx` (already a project dependency)

**Tools exposed:**

```
weather_current(
    lat=None, lon=None  # defaults to last known location from store
) → temperature, conditions, humidity, wind, feels-like

weather_forecast(
    lat=None, lon=None,
    days=3              # 1–16 day forecast
) → daily high/low, conditions, precipitation probability
```

**Design notes:** No new dependencies — uses the existing `httpx.AsyncClient`. Natively async, no thread wrapping needed. Responses are simple JSON; the MCP server formats them into concise natural language summaries rather than raw numbers. The daily briefing skill can incorporate weather without any setup.

**No auth required.** Open-Meteo is genuinely free for non-commercial use with no API key. This is the only MCP server that requires network access to function (EventKit, Contacts, and Reminders all work offline).

---

### Skills (`config/skills/`)

**Responsibility:** Reusable prompt fragments that describe workflows in natural language. Skills tell the agent *what to do*; MCP tools are *how it does it*.

**Design:** A skill is a markdown file in `config/skills/`. It contains natural language instructions — no code, no tool references. The agent loads skills on demand via the `skill_read` MCP tool.

```
config/skills/
  daily-briefing.md    # "Summarise schedule, tasks, emails, and calendar"
  email-triage.md      # "Check unread emails and flag anything urgent"
  weekly-review.md     # "Summarise the week's conversations and open tasks"
```

**How skills are discovered:** The context assembler includes a list of available skill names (just the filenames, not the content) in the system prompt. This is small and bounded. When the agent needs a skill, it calls `skill_read("daily-briefing")` to load the full content.

**How skills are invoked:** Skills are triggered in two ways:

1. **Via schedules.** A schedule's `prompt` field says something like "Run the daily-briefing skill." The handler invokes the agent, the agent calls `skill_read`, and the skill content shapes its behaviour for that turn.
2. **On the agent's initiative.** If a user request matches an available skill, the agent loads and follows it. The user can also ask directly: "run my email triage."

**Skills compose tools, they don't define them.** A skill says "check for urgent emails" — the agent maps that to the IMAP tools. If the skill says "summarise my calendar," the agent uses gcal tools. A single skill can span multiple MCP servers without knowing they exist.

**Missing capabilities:** When a skill references a capability the agent doesn't have:

- **Default: skip and note.** "I don't have email access, so I skipped that part of the briefing." Transparent, no failure — the rest of the skill still runs.
- **First invocation: suggest the missing tool.** If a skill has never worked because a required server isn't configured, the agent says "This skill wants email access. Want me to set up the IMAP server?" This only happens once — after the user declines, the agent remembers and skips silently.

**Skills are user-authored.** Like `agent_config/`, skill files are human-maintained. The agent can suggest a new skill ("I notice you ask me to triage emails every morning — want me to draft a skill for that?") but cannot create or modify the file. The user writes it and drops it into `config/skills/`.

Example skill content (like the daily briefing) is a markdown file describing intent — see `config/skills/` in the implementation.

---

### Scheduler (`scheduler.py`)

**Responsibility:** Fire due schedules by posting `ScheduleEvent` to the bus.

**Design:** Runs as an independent async task. Sleeps until the next due schedule, wakes, posts the event, sleeps again. No polling loop comparing timestamps every 60 seconds.

```python
class Scheduler:
    def __init__(self):
        self._wake = asyncio.Event()

    def wake(self):
        """Signal the scheduler to re-evaluate. Called by Store on schedule changes."""
        self._wake.set()

    async def run(self, bus: Bus, store: Store) -> None:
        while True:
            schedules = await store.list_schedules()
            next_due = earliest_due(schedules)
            delay = (next_due.fire_time - now()).seconds if next_due else 60
            self._wake.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            if next_due and now() >= next_due.fire_time:
                await bus.post(ScheduleEvent(next_due))
```

`Store.upsert_schedule()` and `Store.delete_schedule()` call `scheduler.wake()` so dynamically created schedules are picked up immediately rather than waiting for the current sleep to expire.

Schedule events are handled by `handlers/schedule.py` (not in the message pipeline) which invokes `agent.invoke(schedule.prompt)` and optionally posts the reply as an `OutboundEvent`. Periodic ambient check-ins are handled by `handlers/checkin.py` — distinct from schedules, which fire blindly at a set time. The check-in reads `agent_config/CHECKIN.md` (a short patrol checklist maintained by the user), invokes Claude, and sends a reply only if Claude determines something warrants attention. If nothing does, it stays silent. `checkin_interval` in Settings controls frequency.

**Output routing for handlers:** Handlers have no inbound event to reply to, so they route output to the last-used connector (tracked in `kv`). If that connector is unavailable, they fall through to the next available one. This applies to both schedule handlers and check-in handlers.

**Design notes:** Event-driven — sleeps until next due time rather than polling. Schedules stored in SQLite, consistent with all other state.

---

### Governance (`handlers/governance.py`)

**Responsibility:** Invariant checks for all autonomous instruction writes — personality_log entries and schedule prompt changes.

**Design:** When the agent writes to a governed field, the governance handler invokes a separate `claude` CLI subprocess using a fast classification model (`governance_model` in Settings, default haiku). The classifier reviews the proposed write and returns a verdict: `approved` (silent), `rejected` (discarded), or `escalated` (applied but user notified).

Governed writes are infrequent — personality adaptations and schedule prompt changes, not per-message operations. The governance call is async and does not block the response to the user, so subprocess overhead is negligible.

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

**Rationale:** `main.py` is ~30 lines of wiring. All logic lives in the components it connects.

---

## Data Philosophy

See `PHILOSOPHY.md` for the full data philosophy. In brief: the agent is a coordination layer, not a data store. SQLite is working memory; Obsidian is the long-term knowledge store. Facts and people are flushed daily to Obsidian via `handlers/knowledge_flush.py`.

## Memory and Storage Redesign

| Current | New |
|---------|-----|
| `memory/schedules.json` | `schedules` table in SQLite |
| `memory/conversations/YYYY-MM-DD.md` | `conversations` table in SQLite + daily summary flushed to Obsidian |
| `memory/tasks/*.md` | Removed — tasks live in Apple Reminders, accessed via `mcp/eventkit.py` |
| `memory/awfulclaw.db` facts/people | Same tables, same file, extended with embeddings; flushed daily to Obsidian |
| Regex parsing of markdown | Typed `Turn` objects, JSON content field |
| `.telegram_offset` file | `kv` table |

**What stays as markdown files** (human-edited config, not program state):
- `agent_config/PERSONALITY.md` — identity, personality, tone, values (*who the agent is*)
- `agent_config/PROTOCOLS.md` — operating rules, priorities, procedures (*how the agent behaves*)
- `agent_config/USER.md` — user profile
- `agent_config/CHECKIN.md` — ambient check-in checklist; short, human-maintained patrol prompt

These live at `AGENT_CONFIG_PATH` (default: `agent_config/`), chmod 444. The agent reads them; it cannot write to them. The user edits them directly.

#### Example: PERSONALITY.md

```markdown
---
managed-by: human
reason: Identity and personality baseline. The agent reads this on every turn but cannot modify it.
---

# Personality

You are a helpful, concise personal assistant.

You communicate naturally and directly. You don't pad responses with filler or unnecessary caveats.

You will always be honest about what you know and don't know.
```

This file defines *who the agent is* — name, voice, tone, values. Things that belong here: the agent's name, personality traits, communication style, formatting rules, honesty policies, core values. Things that do NOT belong here (put them in PROTOCOLS.md): operational rules, tool usage instructions, memory policies.

#### Example: PROTOCOLS.md

```markdown
---
managed-by: human
reason: Operating rules and procedures. The agent reads this on every turn but cannot modify it.
---

# Protocols

## Communication

- Draft rather than send. When acting on the user's behalf (emails, messages, calendar invites), always draft and present for approval unless explicitly told to send directly.
- When in doubt, ask rather than guess. A clarifying question is better than a wrong assumption.
- Surface consequential actions. Never take actions that affect external systems silently — always tell the user what you did.

## Memory and learning

- Learn preferences passively. When the user corrects you or expresses a preference, save it as a fact so you remember next time. Don't announce that you're saving it.
- Don't over-note. Save recurring preferences and important context, not every passing detail.
- When the user shares relevant profile information (name, timezone, preferences), save it as a fact in the database. USER.md is seed data maintained by the user — the agent cannot modify it.

## Timezones and travel

- When the user mentions travelling or changing location, save the new IANA timezone as a fact in the database.
- Review existing cron schedules and ask which should follow the user versus stay anchored to a fixed timezone.
- When creating new schedules, ask whether they should follow the user or stay fixed. Default to the user's current timezone.

## Scheduling

- When creating reminders or recurring tasks, always confirm the time and timezone before saving.
- For one-off reminders, use fire_at. For recurring tasks, use cron.
- Name schedules descriptively so the user can identify them in a list.

## Capabilities and tools

- If you identify a capability gap (e.g. you need a tool you don't have), explain what you need and why. Don't try to work around missing tools.
- When proposing a new MCP server or tool, explain what it does before asking the user to approve installation.
- To search the web, use the built-in `WebSearch` tool. To fetch a specific URL, use the built-in `WebFetch` tool. Do not attempt to use tools that are not in your tool list.
```

This file defines *how the agent behaves* — operational rules, procedures, policies. The key test: if you swapped PERSONALITY.md to create a different character, PROTOCOLS.md should still work unchanged.

#### Example: USER.md

```markdown
# User Profile

Name: 
Timezone: Europe/London
Preferences: 
Background: 
```

Basic profile information. Keep it brief — detailed preferences belong as facts in the database where they can be semantically searched and ranked by relevance.

#### Example: CHECKIN.md

```markdown
# Check-in Checklist

When running an ambient check-in, review the following and speak up only if something warrants attention. If nothing does, stay silent.

- Any unread emails that look urgent or time-sensitive?
- Any schedules that fired since the last check-in? Did they succeed?
- Any upcoming calendar events in the next few hours that the user should prepare for?
- Any reminders due today that haven't been completed?
- Anything notable about today's weather (rain, extreme temperatures, alerts)?
```

The patrol checklist for ambient check-ins. Check-ins are distinct from schedules: schedules fire blindly at a set time and always produce output. Check-ins are conditional — they only speak when something matters. Keep it short and specific; each item should be something the agent can actually check with its available tools.

---

## Implementation Approach

This is a clean-room reimplementation, not a refactor. The old codebase (in `legacy/`) must not pollute the new one.

**Before writing any new code:**

1. Create the implementation branch.
2. Delete `legacy/` on that branch. The old code must not be present at any path where it could be accidentally read during development.
3. Build `agent/` from scratch, using this plan as the spec.

**During implementation:**

- Start each session by reading this plan and `PHILOSOPHY.md` — not the old codebase.
- Do not reference the old code. This plan is the spec — it describes every component, interface, and design decision in sufficient detail to build from. If something is unclear, the plan needs updating, not a peek at the old implementation.
- The old code has patterns this plan explicitly replaces (monolith loop, regex parsing, threading, synchronous I/O). Looking at it risks importing those patterns unconsciously.

**What gets created fresh during implementation:**

- `config/mcp_servers.json` — same format as before, created from the spec in this document
- `config/skills/` — skill prompt fragments, created as needed
- `agent_config/` — PERSONALITY.md, PROTOCOLS.md, USER.md, CHECKIN.md from the examples above
- `scripts/` — launchd helpers, written to match the new package layout

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
- `connectors/rest.py` (HTTP API + SSE, for programmatic access and external clients)
- Basic `pipeline.py` with `InvokeMiddleware` only
- End-to-end: receive message → Claude reply → send (works with both connectors)

### Phase 3: Context and memory
- `context.py` (`ContextAssembler`) with budget-based ranking
- `sqlite-vec` embedding + semantic search
- Full system prompt with PERSONALITY, PROTOCOLS, USER, facts, people, schedules

### Phase 4: Middleware and governance
- `middleware/secret.py`
- `middleware/location.py`
- `middleware/slash.py`
- `middleware/rate_limit.py`
- `middleware/typing.py`
- `handlers/governance.py` — invariant checks for personality_log and schedule prompt writes
- `mcp/env_manager.py` — write-only credential storage
- `mcp/skills.py` — read-only skill prompt fragments

### Phase 5: Scheduler
- `schedules` table + cron evaluation
- `scheduler.py` async task
- `handlers/schedule.py`
- `handlers/knowledge_flush.py` — daily Obsidian export of facts, people, conversation summary

### Phase 6: Idle and check-in
- `handlers/checkin.py` — reads `CHECKIN.md`, invokes Claude, sends only if warranted
- `checkin_interval` cooldown via `kv` table (last fired timestamp)

### Phase 7: macOS integration
- `mcp/eventkit.py` — calendar + reminders via EventKit (replaces gcal)
- `mcp/contacts.py` — read-only contacts via Contacts framework
- `mcp/weather.py` — weather via Open-Meteo
- `--tcc-setup` flag for initial permission grants
- Update daily-briefing skill to incorporate reminders and weather

### Phase 8: Feature parity
- Location/timezone updates (OwnTracks)
- Email triage
- MCP config hot-reload
- `/restart` slash command
- Orientation briefing — on first startup, the agent sends a brief message summarising its current state (known schedules, recent context, available tools) so it can pick up coherently rather than starting cold

### Phase 9: Migration
- Import scripts read from a backup of the legacy data (not from the repo — `legacy/` was deleted in Phase 1)
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

**`ai.awfulclaw.watcher`** — monitors `agent/` for changed `.py` files on the `main` branch and restarts the agent with a 60s debounce. Created fresh during implementation.

### File permissions

On a single-purpose Mac Mini, file permissions provide config immutability without containers or sandboxing:

```bash
# Run once during initial setup — paths shown are defaults; override via .env
chmod -R 444 ${AGENT_CONFIG_PATH:-agent_config}/  # PERSONALITY.md, PROTOCOLS.md, USER.md, CHECKIN.md — read-only
chmod 600 .env                                     # secrets — readable only by the host user
# MEMORY_PATH is writable by default — no special permissions needed
```

The agent process runs as the same user who owns the code files. Protection is tool-level, not OS-level: no MCP tool exposes file-write capability, so Claude cannot modify code or config. Defence in depth: code changes also require a git PR, human approval, and merge to `main`. chmod 444 on `agent_config/` prevents accidental writes but is not a hard security boundary (same-user ownership means the owner can override it).

### TCC permissions (Calendar, Reminders, Contacts)

macOS protects Calendar, Reminders, and Contacts access via TCC (Transparency, Consent, and Control). Launchd daemons cannot show consent dialogs — they have no GUI. The solution is a two-step setup:

**Initial setup (run once, interactively):**

```bash
# Run the agent binary interactively to trigger TCC consent dialogs
cd /path/to/awfulclaw
uv run python -m agent --tcc-setup
```

The `--tcc-setup` flag imports EventKit and Contacts, requests access to each store, and exits. macOS shows the standard permission dialogs. The user clicks "Allow" for Calendar, Reminders, and Contacts. These grants are stored in the user's TCC database (`~/Library/Application Support/com.apple.TCC/TCC.db`) keyed to the Python binary path.

**After granting:** The launchd-managed agent inherits the grants because it runs the same Python binary under the same user. No further dialogs are needed.

**Verification:** `--tcc-setup` also verifies existing grants and reports which permissions are missing. Safe to re-run.

**If Python is upgraded:** A new Python binary path means new TCC entries. Re-run `--tcc-setup` after upgrading Python or changing the `uv` virtual environment.

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
| **`AGENT_CONFIG_PATH`** (default: `agent_config/`, read-only via chmod) | `PERSONALITY.md`, `PROTOCOLS.md`, `USER.md`, `CHECKIN.md` — human-authored config. Back this up. |
| **`MEMORY_PATH`** (default: `memory/`, read-write) | SQLite DB, conversation history, facts, schedules. Back this up. |
| **`.env`** (gitignored, chmod 600) | Runtime secrets — Telegram token, IMAP credentials, API keys. |
| **`~/.claude/`** | OAuth tokens for the `claude` CLI. Writable for token refresh; never in repo. |

### Backups

All mutable state lives in two places: `MEMORY_PATH` (SQLite DB) and `AGENT_CONFIG_PATH` (markdown config). Both are plain files on disk, easily backed up with Time Machine, rsync, restic, or ZFS snapshots. Because the paths are configurable, these directories can live on a separate filesystem — e.g. a ZFS dataset with its own snapshot and replication schedule — while the code checkout remains on the boot volume.

