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

The quality of this learning depends on *policy*: the instructions in `SOUL.md` that tell the agent when and what to capture. Good policy means capturing signal (recurring preferences, important context) without over-noting noise. This is a tuning problem, not a mechanism problem — the mechanism (writing facts to SQLite, flushing to Obsidian daily) is sufficient.

## Policy has layers; absolute constraints belong at the capability boundary

Agent behaviour can be constrained at different levels, with different guarantees:

| Layer | Mechanism | Strength |
|-------|-----------|---------|
| **SOUL.md** | Natural language instruction | Soft — Claude is told what not to do |
| **Middleware** | Code that intercepts tool calls | Hard — enforced regardless of Claude's reasoning |
| **MCP server** | Tool implementation that refuses or omits | Hard — the capability does not exist |

For preferences and style ("prefer concise replies"), SOUL.md is the right place.

For absolute constraints ("never send an email on my behalf — only draft"), the right approach is to remove the capability entirely (don't expose a send tool in `mcp/imap.py`) *and* document the reasoning in SOUL.md so the agent understands the intent rather than looking for workarounds.

Soft policy and hard constraint should agree. If they conflict, the hard constraint wins — but the disagreement is a signal that SOUL.md needs updating.

## Agent self-knowledge and the limits of self-modification

The agent should have full visibility of its own working state and architecture. An agent that understands why it can't do something is more cooperative and more useful than one that simply hits a wall. Self-knowledge is desirable. Self-modification is not uniformly desirable — it depends on what is being modified.

Files and configuration are graded by sensitivity:

| Sensitivity | Examples | Agent can read? | Agent can write? |
|-------------|----------|----------------|-----------------|
| **Protected** | `middleware/policy.py`, credential mechanism | Yes | No — ever |
| **Propose-only** | `SOUL.md`, `mcp_servers.json` | Yes | Via PR + human approval only |
| **Working state** | facts, people, schedules, `USER.md` | Yes | Yes |
| **Blind write** | `.env` credential values | No | Yes (write-only, value never readable) |

This grading is made explicit in the files themselves — a header block in each file states its sensitivity level and the reason. This serves two purposes: it is legible to developers reading the code, and legible to the agent reading its own files, so it can explain constraints to the user rather than simply failing.

**Python files** use a module-level docstring:
```python
# SENSITIVITY: protected
# Defines hard policy constraints. Not modifiable by the agent under any circumstances.
# Changes require explicit human review of security implications.
```

**Markdown files** use YAML frontmatter:
```markdown
---
sensitivity: propose-only
modification: pull-request, human approval required
reason: Defines agent identity and behaviour. Unilateral modification would allow the agent to rewrite its own values and constraints.
---
```

### SOUL.md

`SOUL.md` is the agent's identity — its personality, values, and behavioural instructions. It sits at `propose-only` sensitivity. The agent reads it on every turn and can reason about it, but cannot modify it directly.

When the agent identifies a genuine gap or problem in its own instructions — a constraint that's causing unnecessary friction, a missing capability description — it can open a PR proposing a change, with an explanation of the reasoning. A human reviews and approves. This keeps the agent's identity stable while allowing it to participate in its own evolution.

### Code and self-development

The agent *writing* code and the agent *running* code are different things. The agent may identify capability gaps, write new tools or middleware, add tests, and propose a pull request. A human reviews and merges. The file watcher picks up the change and restarts. The agent never becomes the new code unilaterally — a human always stands in the merge path.

The `protected` layer (hard policy constraints, the credential mechanism) is outside even this path. It cannot be proposed for modification by the agent. Changes to it require a human acting entirely outside the agent's awareness.

## The agent proposes; the user approves

The agent can identify capability gaps and suggest solutions — including new MCP servers that would unlock a blocked task — but it does not act unilaterally. Installing and running third-party code is a significant trust boundary. The agent surfaces what it needs and waits for explicit confirmation before proceeding.

This applies especially to third-party MCP servers. The agent may identify a suitable server (from a known registry or by searching), explain what it does and why it's needed, and request approval. Only after confirmation does it install and register the server. This keeps the user in control of what code runs on their machine.

## The agent earns trust through transparency

The agent should never take consequential actions silently. Sending a message, creating a calendar event, modifying a file — these should be surfaced to the user, not assumed. When in doubt, draft rather than send. Propose rather than act. Ask rather than guess.

This is not a technical constraint but a behavioural one, and it belongs in SOUL.md — where it shapes every response rather than being enforced case by case.
