# Runbook

Operational reference for the awfulclaw agent running on the Mac Mini.

## Prerequisites

- macOS (tested on Sequoia)
- [uv](https://docs.astral.sh/uv/) installed at `/opt/homebrew/bin/uv`
- `claude` CLI installed and authenticated (`claude --version` to verify)
- `.env` file at project root (see `.env.example` or copy from another machine)

## First-time setup

```bash
# Install Python deps
uv sync

# Request macOS TCC permissions (Calendar, Reminders, Contacts)
uv run python -m agent.main --tcc-setup

# Install launchd service (starts on login, auto-restarts)
./scripts/install_service.sh
```

## Start / stop / restart

```bash
# Restart agent and web app (picks up code and config changes)
scripts/restart.sh

# Restart only one service
scripts/restart.sh agent
scripts/restart.sh web

# Stop / start manually
launchctl stop gui/$(id -u)/ai.awfulclaw.agent
launchctl start gui/$(id -u)/ai.awfulclaw.agent

# Check status (PID and last exit code)
launchctl list | grep ai.awfulclaw
```

Exit code `-9` in the list output is normal after a restart (SIGKILL of previous instance).

## Logs

```
logs/awfulclaw.out.log   # Inbound/outbound message log, timestamped
logs/awfulclaw.err.log   # Python stderr, warnings, MCP errors
```

Tail live:

```bash
tail -f logs/awfulclaw.out.log
tail -f logs/awfulclaw.err.log
```

Logs are rotated by the `ai.awfulclaw.logrotate` launchd service using `logs/logrotate.conf`.

## Deploying changes

```bash
git pull
scripts/restart.sh
```

No build step needed — `uv run` resolves deps on startup.

## Configuration reference

All variables are set in `.env` with the prefix `AWFULCLAW_`. Nested settings use `__` as delimiter (e.g. `AWFULCLAW_BACKEND__PROVIDER`).

### Timing

| Variable | Default | Meaning |
|----------|---------|---------|
| `AWFULCLAW_POLL_INTERVAL` | `5` s | How often the checkin and summary loops wake up to check whether they need to do anything. Does not affect message latency. |
| `AWFULCLAW_IDLE_INTERVAL` | `14400` s (4 h) | If no messages have been received since the last check-in, the agent fires an early check-in after this many seconds. Keeps the agent active on a quiet day without waiting the full 24 h. |
| `AWFULCLAW_CHECKIN_INTERVAL` | `86400` s (24 h) | Minimum gap between scheduled check-ins when the user is actively messaging. |
| `AWFULCLAW_EMAIL_TRIAGE_INTERVAL` | `900` s (15 min) | How often the email triage job fetches and classifies unread mail. |

### Backend (LLM)

| Variable | Default | Meaning |
|----------|---------|---------|
| `AWFULCLAW_BACKEND__PROVIDER` | `claude` | Primary LLM backend. `claude` uses the local `claude` CLI; `ollama` uses a local Ollama instance. |
| `AWFULCLAW_BACKEND__FALLBACK` | `ollama` | Fallback backend used if the primary fails `FAILURE_THRESHOLD` times in a row. Set to empty string to disable. |
| `AWFULCLAW_BACKEND__CLAUDE_MODEL` | `claude-sonnet-4-6` | Model passed to the `claude` CLI. |
| `AWFULCLAW_BACKEND__OLLAMA_MODEL` | `llama3.2` | Model name served by Ollama. |
| `AWFULCLAW_BACKEND__OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL. |
| `AWFULCLAW_BACKEND__FAILURE_THRESHOLD` | `3` | Consecutive failures before switching to the fallback backend. |
| `AWFULCLAW_BACKEND__PROBE_INTERVAL` | `600` s | How often the agent probes the primary backend to see if it has recovered, so it can switch back automatically. |
| `AWFULCLAW_GOVERNANCE_MODEL` | `claude-haiku-4-5-20251001` | Model used for lightweight governance / self-modification checks (cheaper and faster than the main model). |

### Paths

| Variable | Default | Meaning |
|----------|---------|---------|
| `AWFULCLAW_STATE_PATH` | `state` | Directory for runtime state: SQLite DB, generated info summaries, etc. |
| `AWFULCLAW_PROFILE_PATH` | `profile` | Directory containing `PERSONALITY.md`, `PROTOCOLS.md`, `USER.md`, `CHECKIN.md`. |
| `AWFULCLAW_MCP_CONFIG` | `config/mcp_servers.json` | Path to the MCP server definitions file. |
| `AWFULCLAW_OBSIDIAN_VAULT` | `obsidian` | Path to the Obsidian vault directory, used by the file-read MCP server. |

### Connectors

| Variable | Meaning |
|----------|---------|
| `AWFULCLAW_TELEGRAM__BOT_TOKEN` | Telegram bot token (from BotFather). Required for the Telegram connector. |
| `AWFULCLAW_TELEGRAM__ALLOWED_CHAT_IDS` | Comma-separated list of Telegram chat IDs the bot will respond to. |

### Features

| Variable | Default | Meaning |
|----------|---------|---------|
| `AWFULCLAW_TRANSCRIPTION_ENABLED` | `true` | Enable voice message transcription via Parakeet. Requires `ffmpeg` on PATH. |
| `AWFULCLAW_PARAKEET_MODEL` | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet model used for transcription. |
| `AWFULCLAW_EVENTKIT__ENABLED` | `true` | Enable the EventKit MCP server (Calendar + Reminders). Disable if you don't want to grant calendar access. |
| `AWFULCLAW_CONTACTS__ENABLED` | `true` | Enable the Contacts MCP server. Disable if you don't want to grant contacts access. |

### Optional integrations

| Variable | Meaning |
|----------|---------|
| `AWFULCLAW_IMAP__HOST` | IMAP server hostname. Setting this enables email triage. |
| `AWFULCLAW_IMAP__PORT` | IMAP port (default: `993`). |
| `AWFULCLAW_IMAP__USERNAME` | IMAP login username. |
| `AWFULCLAW_IMAP__PASSWORD` | IMAP password or app-specific password. |
| `AWFULCLAW_OWNTRACKS__URL` | OwnTracks HTTP endpoint. Setting this enables location tracking via the OwnTracks MCP server. |

## MCP server config

MCP servers are defined in `config/mcp_servers.json`. Each entry is a stdio subprocess.

- Secrets are referenced as `${AWFULCLAW_*}` and expanded from `.env` at startup.
- To add a server: add an entry to `mcp_servers.json`, restart the agent.
- Hot-reload is supported: the agent watches `mcp_servers.json` and connects/disconnects servers when the file changes (no restart needed for config-only changes).

## Slash commands (via Telegram)

| Command | Effect |
|---------|--------|
| `/restart` | Sends SIGTERM → agent restarts via launchd keepalive |
| `/schedules` | Lists active schedules |

## SQLite database

State is stored in `state/store.db`. Tables: `facts`, `people`, `conversations`, `schedules`, `kv`, `email_seen_uids`.

```bash
# Inspect
sqlite3 state/store.db .tables
sqlite3 state/store.db "SELECT key, value FROM kv;"
```

## Uninstall service

```bash
./scripts/uninstall_service.sh
```
