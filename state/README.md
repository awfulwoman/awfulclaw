# state/

Runtime state generated and owned by the running agent. Not committed to the repo. Back up with Time Machine, rsync, or your preferred method — losing it means losing conversation history, stored facts, and schedules.

## Contents

- **`store.db`** — Single SQLite database containing all persistent state: facts, people, conversations, schedules, key-value store, and vector embeddings for semantic search.

## Ownership

Written by the agent via MCP tools. Do not edit directly. Safe to delete if you want a clean slate — the agent will recreate it on next start.
