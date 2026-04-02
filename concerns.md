# Design Review: Fitness for Execution & Inconsistencies

## Overall Assessment

The design is well-structured, thorough, and clearly the product of careful thought. The separation of concerns, the middleware pipeline, and the governance model are all sound. That said, there are several inconsistencies and potential execution risks worth flagging.

---

## Inconsistencies Between Documents

### 1. README.md describes the *legacy* architecture, not the new one

The README talks about `memory/SOUL.md`, `<memory:write>` tags, `memory/tasks/`, and the old MCP server list (`memory_write`, `memory_search`, `schedule`, `imap`). DESIGN.md explicitly replaces all of these: SOUL.md becomes PERSONALITY.md + PROTOCOLS.md, `<memory:write>` tags are replaced by MCP tools, tasks are removed (delegated to an external task manager), and the MCP servers are different (`memory`, `schedule`, `imap`, `gcal`, `owntracks`, `env_manager`, `skills`). The README will be actively misleading to anyone (or any agent) reading the repo after implementation begins.

### 2. PHILOSOPHY.md references `PROTOCOLS.md` as read-only `agent_config/` content, but README still references `memory/SOUL.md`

The PHILOSOPHY.md and DESIGN.md agree on the new directory structure (`agent_config/PERSONALITY.md`, `agent_config/PROTOCOLS.md`, etc.). The README is the sole holdout describing the old layout. This is a direct factual conflict.

### 3. CLAUDE.md says "implementation has not started" but README describes a working system

If a developer reads the README, they'll assume the system is built and working. CLAUDE.md says it's a blank-slate reimplementation. These are contradictory signals.

### 4. `.env` security model: PHILOSOPHY.md vs DESIGN.md

- PHILOSOPHY.md says `.env` is "readable only by launchd at startup; the agent has no tool to read it back" and describes values as "loaded by launchd at startup."
- DESIGN.md says "Environment variables are loaded from `.env` by the agent at startup (via `pydantic-settings`), not injected by launchd."

These are opposite mechanisms. If `pydantic-settings` loads `.env` at startup, the agent process *does* have filesystem read access to `.env` (pydantic-settings reads the file directly). The "write-only" security property described in PHILOSOPHY.md would not hold — the agent process could theoretically read `.env` via a file read, even without an `env_get` tool. The protection would be tool-level (no read tool exposed), not OS-level.

### 5. File permissions enforcement gap

PHILOSOPHY.md and DESIGN.md both say code files are protected because "the agent process does not have write permission" — but DESIGN.md also says "The agent process runs as the same user" as the host user. If the agent runs as the same user who owns the code files, standard Unix permissions don't protect anything — the owner can always read and write their own files. The chmod 444 on `agent_config/` can be overridden by the owner. The real protection is that no *tool* exposes file-write outside `memory/`, but that's a soft (tool-level) constraint, not the hard (OS-level) constraint the docs claim.

---

## Logical / Design Concerns

### 6. `sqlite-vec` + `sentence-transformers` adds significant cold-start complexity

Phase 1 requires `Store` with the full schema (including embeddings), and Phase 3 adds `sqlite-vec` and `sentence-transformers`. The `all-MiniLM-L6-v2` model is ~80MB and has its own dependency chain (PyTorch or ONNX runtime). This is a meaningful dependency burden for a project that prides itself on simplicity (no Docker, no containers, just `uv sync`). The design doesn't discuss fallback behavior if the embedding model fails to load or if `sqlite-vec` isn't available. This could be a significant friction point during initial setup.

### 7. The `ClaudeClient` design assumes `claude --print --output-format stream-json` supports passing full conversation history and MCP config

The `claude` CLI is primarily an interactive tool. The design assumes it can accept arbitrary multi-turn conversation history, a system prompt, and MCP server config via command-line arguments for one-shot invocations. The exact CLI flags and their behavior should be verified. The `--print` flag typically outputs a single response; managing multi-turn context externally and replaying it each invocation could hit CLI argument length limits or undocumented behavior.

### 8. Governance layer uses `claude-haiku-4-5` via the CLI subprocess — but the CLI uses OAuth, not an API key

The governance layer calls a *second* Claude invocation per governed write. This means every personality_log entry or schedule prompt change spawns another `claude` CLI subprocess. The design doesn't discuss: (a) latency impact of spawning a subprocess for each governance check, (b) whether the CLI supports model selection per invocation (`--model claude-haiku-4-5-20251001`), or (c) rate limiting on the OAuth-based CLI for rapid successive calls.

### 9. Watcher monitors `app/` but the package is `agent/`

DESIGN.md line 829: "monitors `app/` for changed `.py` files." The package layout (line 24-66) uses `agent/`, not `app/`. This is a factual error in the spec.

### 10. Scheduler sleep-until design has a notification gap

The scheduler sleeps until the next due time, then wakes and fires. But if a *new* schedule is created (via MCP tool) while the scheduler is sleeping, it won't wake up until the previous sleep expires. The design mentions no mechanism (e.g., an `asyncio.Event` to interrupt sleep) to handle dynamically added schedules. A schedule created for 5 minutes from now could be missed if the scheduler is sleeping for 60 minutes waiting on a distant future event.

### 11. Check-in handler has no obvious way to reach the user

`handlers/checkin.py` "invokes Claude, and sends a reply only if Claude determines something warrants attention." But the handler invokes `agent.invoke(prompt)` which returns a string. How does that string get routed to the user? It would need to post an `OutboundEvent` to the bus, but the handler needs to know which channel/connector to target. The design doesn't specify how handlers select the output channel (unlike the middleware pipeline where the inbound event carries channel info).

### 12. PROTOCOLS.md example says "Update USER.md fields" — but USER.md is chmod 444

The example PROTOCOLS.md (line 654) instructs the agent to "Update USER.md fields when the user shares relevant profile information." But USER.md lives in `agent_config/` which is chmod 444 (read-only). The agent cannot write to it. This is a direct contradiction within DESIGN.md itself.

---

## Minor Issues

- **Phase 8 (Migration)** references importing from `schedules.json` and `conversations/YYYY-MM-DD.md` — files from the legacy system. But Phase 1 step says "delete `legacy/`" before writing new code. The migration scripts would need the old data to exist somewhere. This ordering needs clarification.
- The README's optional env var `AWFULCLAW_MODEL=claude-sonnet-4-6` doesn't match DESIGN.md's `Settings.model` default — the env var prefix convention (`AWFULCLAW_` in README vs. bare names in DESIGN.md's pydantic-settings) is unspecified.
- DESIGN.md mentions a "file watcher" (`ai.awfulclaw.watcher`) and says it "Already exists in `scripts/`", but this refers to the legacy codebase that will be deleted.

---

## Recommended Actions (Priority Order)

1. **Fix the `.env` security model contradiction** — decide whether pydantic-settings reads `.env` or launchd injects env vars, and align both documents.
2. **Fix the file permissions claim** — acknowledge that same-user ownership means tool-level protection, not OS-level. Or run the agent as a different user.
3. **Fix `app/` → `agent/`** in the watcher description.
4. **Fix the USER.md write instruction** in the PROTOCOLS.md example (can't write to a read-only file).
5. **Update README.md** to reflect the new architecture, or add a clear banner that it describes the legacy system.
6. **Add a scheduler wake-up mechanism** for dynamically created schedules.
7. **Clarify handler → output routing** (how do scheduled/check-in replies reach the user?).
