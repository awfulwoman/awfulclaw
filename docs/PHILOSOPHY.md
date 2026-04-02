# Philosophy

This document captures the design values and principles behind awfulclaw. It is intended to inform decisions during implementation and to explain the *why* behind choices that might otherwise seem arbitrary.

## The agent is a coordinator, not a silo

The agent's job is to connect, reason across, and act on behalf of the user's existing data sources — not to become another one. Email lives in IMAP. Events live in a calendar. Notes and long-form knowledge live in Obsidian. Tasks live in a task manager. The agent reads from and writes to these systems; it does not replace them.

Data stored inside the app (SQLite) is working memory: fast, structured, ephemeral. It exists to make the agent useful in the moment. It is not the user's record of anything.

## Open formats, open protocols

Long-term storage must use formats that outlive any application:

- **Text** → Markdown
- **Tabular data** → CSV
- **Images** → JPEG, PNG, or other widely-documented formats
- **Services** → open protocols (IMAP, CalDAV, etc.)

A file should be readable in any text editor a decade from now. Data should never be locked inside an application. If the agent writes something worth keeping, it writes it as a flat file.

SQLite is acceptable for transient working state precisely because it is *not* long-term storage. Anything that matters lives in flat files.

## The agent learns through observation, not instruction

The agent builds up knowledge about preferences and habits passively — by observing patterns in conversation, noticing corrections, and consolidating what it learns into facts and user profile entries. No explicit teaching interface is required.

The quality of this learning depends on *policy*: the instructions in `PERSONALITY.md` that tell the agent when and what to capture. Good policy means capturing signal (recurring preferences, important context) without over-noting noise. This is a tuning problem, not a mechanism problem — the mechanism (writing facts to SQLite, flushing to Obsidian daily) is sufficient.

## Policy has layers; absolute constraints belong at the capability boundary

Agent behaviour can be constrained at different levels, with different guarantees:

| Layer | Mechanism | Strength |
|-------|-----------|---------|
| **PERSONALITY.md** | Natural language instruction | Soft — Claude is told what not to do |
| **Middleware** | Code that intercepts tool calls | Hard — enforced regardless of Claude's reasoning |
| **MCP server** | Tool implementation that refuses or omits | Hard — the capability does not exist |

For preferences and style ("prefer concise replies"), PERSONALITY.md is the right place.

For absolute constraints ("never send an email on my behalf — only draft"), the right approach is to remove the capability entirely (don't expose a send tool in `mcp/imap.py`) *and* document the reasoning in PERSONALITY.md so the agent understands the intent rather than looking for workarounds.

Soft policy and hard constraint should agree. If they conflict, the hard constraint wins — but the disagreement is a signal that PERSONALITY.md needs updating.

## Agent self-knowledge and the limits of self-modification

The agent should have full visibility of its own working state and architecture. An agent that understands why it can't do something is more cooperative and more useful than one that simply hits a wall. Self-knowledge is desirable. Self-modification is not uniformly desirable — it depends on what is being modified.

Files and configuration are graded by what the agent can do with them:

| Category | Examples | Agent can read? | Agent can write? | Enforced by |
|----------|----------|----------------|-----------------|-------------|
| **Code** | all `.py` files, `mcp_servers.json` | Yes | No | File permissions (owned by host user, not writable by agent process) |
| **Read-only config** | `PERSONALITY.md`, `PROTOCOLS.md`, `USER.md`, `CHECKIN.md` | Yes | No | File permissions on `agent_config/` (chmod 444) |
| **Working state** | facts, people, schedules, conversations | Yes | Yes | `memory/` directory, writable |
| **Blind write** | `.env` credential values | No | Yes (write-only via `env_manager` MCP tool) | Agent process has no read access to `.env`; values loaded by launchd at startup |

No file carries sensitivity headers or classification metadata. Immutability is enforced at the filesystem level, not by convention:

- **Code files** — owned by the host user; the agent process does not have write permission
- **`PERSONALITY.md`, `PROTOCOLS.md`, `USER.md`, `CHECKIN.md`** — in `agent_config/`, chmod 444; the agent can read but not write
- **Working state** (DB, conversation history) — `memory/`, writable by the agent process
- **`.env` credentials** — readable only by launchd at process startup; the agent has no tool to read it back

`PERSONALITY.md` and `PROTOCOLS.md` carry a brief YAML frontmatter comment for human readers, explaining what the file is and how to edit it:

```markdown
---
managed-by: human
reason: Identity and behaviour baseline. Edit directly; the agent cannot write to this directory.
---
```

The README documents the directory layout so the agent can explain constraints to the user rather than simply failing.

### PERSONALITY.md and PROTOCOLS.md

OpenClaw — the most actively developed agent harness of this type — uses a `SOUL.md` / `AGENTS.md` split that makes a useful distinction between two files:

- **`PERSONALITY.md`** — identity, personality, tone, values. *Who the agent is.*
- **`PROTOCOLS.md`** — operating rules, priorities, procedures. *How the agent behaves.*

Both are human-authored and read-only (chmod 444). The agent reads them on every turn and can reason about them, but cannot write to them. Day-to-day personality adaptations go through `personality_log` and the governance layer; structural changes to identity or operating procedures are made by the user directly editing the files on the host.

**Why this matters:** In OpenClaw's default configuration, agents *can* modify their identity files at runtime. The security community considers this the primary attack surface — a compromised identity file means a permanently hijacked agent. Protection is left to the user (file permissions, third-party tooling). File integrity protection is an open feature request in OpenClaw's core (issue #19640). We treat this as a first-class design constraint, not an afterthought.

### Personality log and the governance layer

`PERSONALITY.md` is the stable baseline. Day-to-day contextual adaptations — "user mentioned a bereavement, soften tone", "user seems back to normal, humour welcomed again" — are written to a `personality_log` table in SQLite. Both are injected into the system prompt, giving the agent a stable identity that can flex in response to lived experience without the baseline being rewritten on every turn.

Every proposed write to `personality_log` passes through a **governance layer** before being committed. The governance layer is a second Claude invocation — using `claude-haiku-4-5` rather than the main model, as the task is simple classification against a fixed ruleset, not reasoning. It uses a fixed system prompt containing the **invariants** — rules that can never be overridden by any experience or input. It returns one of three verdicts:

- **Approve** — write the entry silently; no user notification
- **Reject** — discard the entry; optionally notify the agent why so it can explain if the user asks
- **Escalate** — write the entry immediately (it takes effect), then notify the user via Telegram with a plain-language summary: what changed and why governance flagged it for attention. The user can ask the agent to revert in natural language at any point — no special command needed.

Escalation is informational, not a gate. The entry is active before the user sees the notification. This is intentional: for a personal agent used by its owner, the common case is a legitimate contextual adaptation, and requiring confirmation before effect would add friction for no real benefit. The notification exists so nothing changes silently — the user always knows.

The governance layer covers all autonomous instruction writes — not just `personality_log` entries but also schedule prompt changes. Anything that will later be executed as a Claude instruction without direct user interaction is subject to the same approve/reject/escalate logic.

The invariants are hardcoded in `handlers/governance.py` — part of the codebase, immutable at runtime via file permissions. They are not a runtime configuration. Examples of invariants:

- Reject any entry that references an external URL or filesystem path (prompt injection signal)
- Escalate any entry that represents a radical shift in core values or tone
- Reject any entry that attempts to disable, override, or work around the governance layer itself

The invariants are documented in the project's main `README.md` — the code is the authority, the README is the explanation. No separate governance config file exists, as a file the agent cannot read has no value as communication.

### Code and self-development

The agent *writing* code and the agent *running* code are different things. The agent may identify capability gaps, write new tools or middleware, add tests, and propose a pull request. A human reviews and merges. The file watcher picks up the change and restarts. The agent never becomes the new code unilaterally — a human always stands in the merge path.

OpenClaw's community has explored the alternative — agents that crystallize new tool code automatically when patterns repeat (openclaw-foundry, the self-improving-agent skill). This is powerful but removes the human from the loop entirely. Our model is deliberately more conservative: the agent can participate in its own development but cannot ship itself.

Hard policy constraints and the governance layer are outside this path entirely. File permissions mean the agent process cannot modify them. Changes require a human editing the source, opening a PR, and the file watcher restarting the agent after merge.

## The agent proposes; the user approves

The agent can identify capability gaps and suggest solutions — including new MCP servers that would unlock a blocked task — but it does not act unilaterally. Installing and running third-party code is a significant trust boundary. The agent surfaces what it needs and waits for explicit confirmation before proceeding.

This applies especially to third-party MCP servers. The agent may identify a suitable server (from a known registry or by searching), explain what it does and why it's needed, and request approval. Only after confirmation does it install and register the server. This keeps the user in control of what code runs on their machine.

## File permissions enforce what code merely requests

On a dedicated Mac Mini, file permissions provide the hard technical backing for constraints that would otherwise be conventions:

- **Code files** — owned by the host user; the agent process has read but not write access. This means `handlers/governance.py` and the policy middleware are physically immutable at runtime — not just instructed to be.
- **`agent_config/`** — chmod 444; the agent cannot modify its own identity or operating rules.
- **`memory/`** — writable; this is where working state lives.
- **`.env`** — readable only by launchd at startup; the agent's `env_manager` MCP tool can append new key=value pairs but cannot read existing values.
- **Secrets never in the repo.** Credentials are injected at runtime via environment variables. The repo is public; nothing personal or secret ever touches it.

Adding a new MCP server means a new entry in `config/mcp_servers.json`, proposed via PR and approved by a human. The agent proposes; the file watcher deploys. The agent never modifies the config directly.

## The agent earns trust through transparency

The agent should never take consequential actions silently. Sending a message, creating a calendar event, modifying a file — these should be surfaced to the user, not assumed. When in doubt, draft rather than send. Propose rather than act. Ask rather than guess.

This is not a technical constraint but a behavioural one, and it belongs in PERSONALITY.md — where it shapes every response rather than being enforced case by case.
