# Web Interface Design

**Date:** 2026-04-06

## Overview

A separate, Docker-deployable web application providing a browser-based chat interface and status sidebar for awfulclaw. The web app proxies all requests to the agent's existing REST API — no direct database or file access.

## Goals

- Chat window for conversing with the agent from a browser
- Sidebar showing current agent setup: MCP server status, active schedules, KV config, and links to profile documents
- Profile pages showing full content of personality/protocols/user/checkin files
- Deployable anywhere (Docker), while the agent continues to run natively on the Mac Mini
- No authentication — access controlled by bind address

## Architecture

```
Browser
  └─ GET /             → index.html  (chat + sidebar)
  └─ GET /info/{name}  → info.html   (profile content page)
  └─ POST /proxy/chat  ─┐
  └─ GET /proxy/api/*  ─┤─→ web/app.py (Starlette proxy)
  └─ GET /static/*     ─┘       │
                                 └─→ Agent REST API (localhost:8080)
                                       POST /chat
                                       GET /api/status
                                       GET /api/info/{name}
```

The web app is a thin Starlette server. It serves static files and HTML pages, and proxies API calls to the agent. The agent URL is configured via environment variable.

## Repository structure

```
web/
  app.py                  # Starlette app — proxy routes + page routes
  requirements.txt
  Dockerfile
  docker-compose.yml
  static/
    index.html            # chat + sidebar page
    info.html             # profile content page
    style.css
    components/
      agent-chat.js       # <agent-chat> web component
      agent-sidebar.js    # <agent-sidebar> web component
      profile-viewer.js   # <profile-viewer> web component
```

## Routes

### Web app (`web/app.py`)

| Route | Description |
|-------|-------------|
| `GET /` | Serves `index.html` |
| `GET /info/{name}` | Serves `info.html` for the named profile |
| `POST /proxy/chat` | Proxies to agent `POST /chat` |
| `GET /proxy/api/status` | Proxies to agent `GET /api/status` |
| `GET /proxy/api/info/{name}` | Proxies to agent `GET /api/info/{name}` |
| `GET /static/...` | Static files |

### New agent endpoints (added to `agent/connectors/rest.py`)

| Route | Returns |
|-------|---------|
| `GET /api/status` | MCP server list + connected status, active schedules, non-secret KV entries |
| `GET /api/info/{name}` | Raw markdown of the named profile file; 404 for unknown names |

Valid `name` values: `personality`, `protocols`, `user`, `checkin` — mapping to `profile/PERSONALITY.md` etc.

## Web components

Three browser-native Custom Elements with Shadow DOM, loaded as ES modules. No build step, no framework.

### `<agent-chat>`

- Starts empty on load
- User submits message → `POST /proxy/chat` → appends reply to message list
- Shows typing indicator while waiting for response
- Scrolls to bottom on new messages
- Handles timeout and error states

### `<agent-sidebar>`

- Fetches `GET /proxy/api/status` on connect, refreshes every 60s
- Renders four sections:
  - **Profile** — links to `/info/personality`, `/info/protocols`, `/info/user`, `/info/checkin`
  - **MCP Servers** — name + green/red status dot
  - **Schedules** — name + cron expression
  - **Config** — non-secret KV entries as key/value pairs

### `<profile-viewer>`

- Used on `info.html`
- Derives profile name from `window.location.pathname` (last path segment) on connect
- Fetches `GET /proxy/api/info/{name}`
- Renders returned markdown as HTML using a client-side markdown parser
- `info.html` is fully static — no server-side templating needed

## Pages

### `index.html`

Two-column layout: `<agent-chat>` on the left (primary), `<agent-sidebar>` on the right.

### `info.html`

Single-column page with `<profile-viewer>` and a back link to `/`.

## Agent changes

### New endpoints

Two new route handlers in `agent/connectors/rest.py`:

**`GET /api/status`** reads from objects already held by the app:
- `MCPClient` — server names and connected status
- `store.list_schedules()` — active schedules
- `store.kv_get_all()` — KV entries, filtered to exclude secret values (those written via `secret://`)

**`GET /api/info/{name}`** reads and returns one of the four profile files as plain text (markdown). Rejects unknown names with 404.

### Bind address

Change `host="0.0.0.0"` → `host="127.0.0.1"` in `RESTConnector.start()`. The agent REST API is no longer exposed on external interfaces. The web app proxy is the intended external caller.

## Configuration

### Web app environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_URL` | `http://localhost:8080` | Base URL of the agent REST API |
| `PORT` | `3000` | Port the web app binds to |
| `HOST` | `127.0.0.1` | Bind address (`0.0.0.0` when running in Docker) |

### `web/Dockerfile`

- Base: `python:3.12-slim`
- Installs `uv`, then deps from `requirements.txt`
- Copies app and static files
- Default bind: `HOST=0.0.0.0`

### `web/docker-compose.yml`

Example showing the web app connecting to the agent running on the host machine:

```yaml
services:
  web:
    build: .
    ports:
      - "3000:3000"
    environment:
      AGENT_URL: http://host.docker.internal:8080
      HOST: 0.0.0.0
```

`host.docker.internal` resolves to the Docker host on macOS. On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]`.
