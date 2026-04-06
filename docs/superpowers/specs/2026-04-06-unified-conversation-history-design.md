# Unified Conversation History Design

**Date:** 2026-04-06

## Overview

All connectors (Telegram, web, and future ones) write to a single shared channel (`"primary"`) in the existing `conversations` SQLite table. A new `connector` field records which connector each turn came from. The web chat interface loads this unified history on page load, rendering each message with a connector label (user turns only) and a timestamp.

## Goals

- Agent context is unified across connectors — the agent remembers things said on Telegram when you switch to the web UI and vice versa
- Web chat pre-populates with recent history on load, surviving page reloads
- Each message in the web view shows which connector it came from and when it was sent
- No changes to how the agent reasons — it already uses `recent_turns(channel, N)` for context

## Architecture

```
Telegram connector  ─┐
REST /chat          ─┤─→ channel="primary", connector=<name> → conversations table
Future connectors   ─┘                                              │
                                                                    ↓
                                              GET /api/history → recent_turns("primary", 50)
                                                                    │
                                              GET /proxy/api/history (web proxy)
                                                                    │
                                              <agent-chat> loads on connectedCallback
```

## Data Layer

### Schema change

Add a `connector` column to the `conversations` table:

```sql
ALTER TABLE conversations ADD COLUMN connector TEXT NOT NULL DEFAULT 'unknown';
```

### Migration

A standalone migration script (`scripts/migrate_primary_channel.py`) runs once manually. It is idempotent: it checks whether any `channel='primary'` rows already exist before updating. The `ALTER TABLE` is guarded the same way (SQLite errors if the column already exists, so the script checks `PRAGMA table_info(conversations)` first).

```sql
-- Add connector column if not present
ALTER TABLE conversations ADD COLUMN connector TEXT NOT NULL DEFAULT 'unknown';

-- Migrate Telegram history to primary channel
UPDATE conversations SET connector = 'telegram' WHERE channel = '888261035';
UPDATE conversations SET channel = 'primary'   WHERE channel = '888261035';
```

The Telegram chat ID (`888261035`) is the only non-primary channel with real conversation history. The script is not run at agent startup — it is a one-off operation.

### Store changes

- `Turn` dataclass gains a `connector: str` field (default `'unknown'`)
- `Store.add_turn(channel, role, content, connector='unknown')` — new optional parameter
- `Store.recent_turns(channel, limit)` — unchanged; returns `Turn` objects now including `connector`

## Connector Changes

**Telegram connector** (`agent/connectors/telegram.py`): use `channel="primary"` instead of `str(chat_id)` when constructing `InboundEvent`.

**REST `/chat`** (`agent/connectors/rest.py`): use `channel="primary"` instead of `str(uuid4())` when constructing `InboundEvent`.

**REST `/event`** (fire-and-forget, used by scheduled jobs and webhooks): keeps its per-request UUID channel — these are not user conversations and must not appear in the primary history.

**`InboundEvent.connector_name`** is already set by each connector ("telegram", "rest"). No changes needed there.

## Agent Changes

`Agent.reply(event)` passes `connector=event.connector_name` to both `store.add_turn()` calls — for the user turn and the assistant turn. Assistant turns carry the same connector as the message they're responding to.

## New Agent Endpoint

`GET /api/history` in `agent/connectors/rest.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `50` | Number of most recent turns to return |

Response:

```json
{
  "turns": [
    {
      "role": "user",
      "content": "what's on my calendar?",
      "timestamp": "2026-04-06T09:12:33Z",
      "connector": "telegram"
    },
    {
      "role": "assistant",
      "content": "You have two events...",
      "timestamp": "2026-04-06T09:12:41Z",
      "connector": "telegram"
    }
  ]
}
```

Turns are ordered oldest-first. `connector` varies meaningfully only on user turns; assistant turns carry the connector of the message they responded to.

## Web App Changes

### New proxy route

`GET /proxy/api/history` in `web/app.py` — proxies straight to `GET /api/history?limit=50`, same response shape.

### `<agent-chat>` component

On `connectedCallback`, fetch `/proxy/api/history` and pre-populate `this._messages` before rendering. Each message object gains two new fields: `connector` (string) and `timestamp` (ISO string).

**Rendering:**
- Every message (user and assistant) shows a dim timestamp below the bubble, formatted using `new Date(ts).toLocaleTimeString()` (browser local timezone, short form e.g. `09:12`) with the full ISO timestamp in a `title` attribute for hover.
- User turns also show a dim connector label (`web`, `telegram`) above or inline with the bubble.
- Assistant turns show no connector label.

Visual sketch:
```
                     telegram · 09:12
                  what's on my calendar?   ←user bubble
                                  09:12:41
  You have two events...                   ←agent bubble

                          web · 21:04
          remind me 30 min before          ←user bubble
                                  21:04:09
  Done — reminder set for 13:30.           ←agent bubble
```

New messages sent during the current session have their timestamp set from the response or locally at send time.

## Testing

### Agent tests

- `test_store_crud.py`: `test_add_turn_with_connector` — verify `Turn.connector` is stored and returned
- `test_store_crud.py`: migration test — rows with old Telegram channel are updated to `"primary"` with `connector="telegram"`
- `test_connectors_rest.py`: `test_history_endpoint` — returns turns from primary channel, respects `limit`

### Web tests

- `test_app.py`: `test_proxy_history_forwards` — proxy route hits agent and returns turns

### No automated test for the web component rendering — visual verification only.
