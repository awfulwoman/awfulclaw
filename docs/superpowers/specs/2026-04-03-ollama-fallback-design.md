# Multi-Backend LLM Design

**Date:** 2026-04-03
**Status:** Approved

## Overview

Introduce a pluggable LLM backend system so the agent can switch between Claude and any other model (ollama, OpenAI, Gemini, etc.) — either automatically on failure or by explicit config. Ollama is the first non-Claude backend, providing a local fallback. Full MCP tool capability is preserved on all backends via a shared `MCPRunner`.

## Goals

- Pluggable backends: adding a new LLM requires only a new `LLMClient` implementation
- Seamless automatic fallback from primary to fallback backend on consecutive failures
- Full MCP tool support on all backends
- Transparent: user is notified when backend switches
- Safe: `AWFULCLAW_BACKEND` env var locks to a specific backend, preventing any switching (useful for testing)

## Non-Goals

- Performance parity between backends
- Streaming responses
- Automatic recovery without user confirmation
- More than two backends active simultaneously (primary + fallback)

---

## Architecture

### LLMClient Protocol

New file `agent/llm_client.py` defines a `LLMClient` protocol:

```python
class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        mcp_config_path: Path,
        allowed_tools: list[str],
    ) -> str: ...
```

Each backend implements this interface and handles its own tool-calling strategy:
- **Claude CLI backends**: tool use handled natively by the CLI
- **HTTP API backends** (ollama, OpenAI, etc.): tool use handled via `MCPRunner` loop

`Agent` is typed against `LLMClient` and knows nothing about which backend is active.

### MCPRunner

New file `agent/mcp_runner.py`. Shared by any backend that needs to orchestrate tool calls directly. Manages stdio connections to MCP servers for the duration of a single completion call.

- `list_tools() -> list[ToolSchema]` — initialises servers, fetches schemas
- `call_tool(name, args) -> str` — routes call to the appropriate server
- Tears down server processes on exit (context manager)

Only spawns servers with a `command` key (same filter as `ClaudeClient`). Uses the Anthropic `mcp` Python SDK for the stdio protocol.

### OllamaClient

New file `agent/ollama_client.py`. First non-Claude backend implementation.

On `complete()`:
1. Start MCP servers via `MCPRunner`, fetch tool schemas, convert to ollama's OpenAI-compatible tool format
2. POST to `/api/chat` with messages + tools
3. If response contains `tool_calls`: execute each via `MCPRunner`, append `tool` role messages, loop
4. Return final text response

Future HTTP API backends (OpenAI, Gemini) follow the same pattern with their own tool format conversion.

### Backend Factory

In `agent/main.py`, a `build_client(name: str, settings: Settings) -> LLMClient` function maps backend names to client instances:

```python
def build_client(name: str, settings: Settings) -> LLMClient:
    match name:
        case "claude": return ClaudeClient(settings.model)
        case "ollama": return OllamaClient(settings.ollama_url, settings.ollama_model)
        case _: raise ValueError(f"Unknown backend: {name}")
```

Adding a new backend = new `LLMClient` class + one new `case` here.

### BackendManager

New file `agent/backend_manager.py`. Generic — takes a `primary: LLMClient` and `fallback: LLMClient`, knows nothing specific about Claude or ollama. `Agent` calls `backend_manager.complete()` instead of `client.complete()` directly.

**Modes** (controlled by `AWFULCLAW_BACKEND` env var):

| `AWFULCLAW_BACKEND` | Behaviour |
|---|---|
| any backend name | Locked to that backend. No switching, no probe. |
| unset | Automatic mode: primary → fallback on failures. |

**Automatic mode state machine:**

- Starts on primary backend (default: `claude`)
- Tracks `consecutive_failures: int`; resets to 0 on success
- After `fallback_failure_threshold` consecutive failures: switch to fallback, publish Telegram notification
- Background probe runs every `fallback_probe_interval` seconds against the primary backend
- For `claude` primary: probe runs `claude --version` (cheap, no API call)
- For other primaries: probe makes a minimal completion call
- When probe succeeds while on fallback: publish Telegram notification ("Primary backend is back — reply /use-primary to switch")
- `/use-primary` slash command: switches back to primary, resets failure count

**Notifications** are published onto the bus as outbound events to the user's Telegram chat.

### Slash Command

`/use-primary` added to the existing slash commands middleware. Only acts in automatic mode (unset `AWFULCLAW_BACKEND`); silently ignored if `AWFULCLAW_BACKEND` is set.

---

## Configuration

New `Settings` fields:

```python
primary_backend: str = "claude"
fallback_backend: str = "ollama"
ollama_url: str = "http://localhost:11434"
ollama_model: str = "llama3.2"
fallback_failure_threshold: int = 3
fallback_probe_interval: int = 600  # seconds, default 10 minutes
```

`AWFULCLAW_BACKEND` is read directly from the environment at startup (not a `Settings` field) — it controls how components are wired, not runtime behaviour.

---

## Data Flow

```
Agent.reply()
    → BackendManager.complete()
        → [automatic] primary LLMClient.complete()   ← normal path
                      on failure: increment counter
                      at threshold: switch, notify
        → [automatic] fallback LLMClient.complete()  ← fallback path

HTTP API backends (e.g. OllamaClient):
    MCPRunner: start servers, list tools
    POST /api/chat loop with tool_calls
    MCPRunner: call tools, feed results back
```

---

## Error Handling

- `ClaudeClient` already retries 3 times before raising. `BackendManager` counts a failure after all retries are exhausted.
- Fallback backend raises if unreachable (no fallback from the fallback).
- `MCPRunner` raises if a tool call fails; the client propagates the error back to the user as a reply.

---

## Testing

Key test cases:

- `BackendManager` switches to fallback after N consecutive primary failures
- `BackendManager` stays on named backend when `AWFULCLAW_BACKEND` is set
- Probe detects primary recovery and publishes Telegram notification
- `/use-primary` switches back only in automatic mode; no-op when `AWFULCLAW_BACKEND` is set
- `OllamaClient` tool loop: zero tool calls, one round, multiple rounds
- `MCPRunner`: starts servers, lists tools, calls tools, tears down cleanly
- Backend factory raises on unknown backend name

Test infrastructure: existing pytest suite. Mock HTTP APIs with `aioresponses` or `respx`. Mock MCP servers with in-process stubs.

---

## Files Changed

| File | Change |
|---|---|
| `agent/llm_client.py` | New — `LLMClient` protocol |
| `agent/mcp_runner.py` | New — `MCPRunner` (shared by HTTP API backends) |
| `agent/ollama_client.py` | New — `OllamaClient` |
| `agent/backend_manager.py` | New — generic `BackendManager` |
| `agent/claude_client.py` | Minor — add protocol conformance annotation |
| `agent/agent.py` | Minor — typed against `LLMClient`, uses `BackendManager` |
| `agent/config.py` | Add 6 new `Settings` fields |
| `agent/middleware/slash_commands.py` | Add `/use-primary` handler |
| `agent/main.py` | Add `build_client()` factory, wire `BackendManager` based on `AWFULCLAW_BACKEND` |
| `tests/` | New tests for all above |
