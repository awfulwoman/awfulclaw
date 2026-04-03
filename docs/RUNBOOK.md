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
# Restart (picks up code changes and config changes)
launchctl kickstart -k gui/$(id -u)/ai.awfulclaw.agent

# Stop
launchctl stop gui/$(id -u)/ai.awfulclaw.agent

# Start
launchctl start gui/$(id -u)/ai.awfulclaw.agent

# Check status (PID and last exit code)
launchctl list | grep ai.awfulclaw.agent
```

Exit code `-9` in the list output is normal after a `kickstart -k` (SIGKILL of previous instance).

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
launchctl kickstart -k gui/$(id -u)/ai.awfulclaw.agent
```

No build step needed — `uv run` resolves deps on startup.

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

State is stored in `state/store.db`. Tables: `facts`, `people`, `conversations`, `schedules`, `kv`.

```bash
# Inspect
sqlite3 state/store.db .tables
sqlite3 state/store.db "SELECT key, value FROM kv;"
```

## Uninstall service

```bash
./scripts/uninstall_service.sh
```
