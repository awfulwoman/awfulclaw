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

## The agent earns trust through transparency

The agent should never take consequential actions silently. Sending a message, creating a calendar event, modifying a file — these should be surfaced to the user, not assumed. When in doubt, draft rather than send. Propose rather than act. Ask rather than guess.

This is not a technical constraint but a behavioural one, and it belongs in SOUL.md — where it shapes every response rather than being enforced case by case.
