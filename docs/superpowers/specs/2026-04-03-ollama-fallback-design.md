# Ollama Fallback Design

**Date:** 2026-04-03
**Status:** Approved

## Overview

Add ollama as a fallback LLM backend so the agent can continue operating if the Claude CLI becomes unavailable or too expensive. The integration preserves full tool/MCP capability by implementing an MCP orchestration loop inside `OllamaClient`.

## Goals

- Seamless fallback to a locally-running ollama model
- Full MCP tool support (memory, schedule, calendar, etc.) on ollama
- Transparent: user is notified when backend switches
- Safe: `AWFULCLAW_FALLBACK` env var locks the backend, preventing any switching (useful for testing)

## Non-Goals

- Performance parity with Claude
- Streaming responses
- Automatic recovery without user confirmation

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

`ClaudeClient` already satisfies this shape. `OllamaClient` implements it. `Agent` is typed against the protocol.

### OllamaClient

New file `agent/ollama_client.py`.

On `complete()`:
1. Start MCP servers via `MCPRunner`, fetch tool schemas, convert to ollama's OpenAI-compatible tool format
2. POST to `/api/chat` with messages + tools
3. If response contains `tool_calls`: execute each via `MCPRunner`, append `tool` role messages, loop
4. Return final text response

Uses the Anthropic `mcp` Python SDK for the stdio protocol rather than hand-rolling JSON-RPC.

### MCPRunner

New file `agent/mcp_runner.py`. Manages stdio connections to MCP servers for the duration of a single completion call.

- `list_tools() -> list[ToolSchema]` — initialises servers, fetches schemas
- `call_tool(name, args) -> str` — routes call to the appropriate server
- Tears down server processes on exit (context manager)

Only spawns servers with a `command` key (same filter as `ClaudeClient`).

### BackendManager

New file `agent/backend_manager.py`. `Agent` calls `backend_manager.complete()` instead of `client.complete()` directly.

**Modes** (controlled by `AWFULCLAW_FALLBACK` env var):

| `AWFULCLAW_FALLBACK` | Behaviour |
|---|---|
| `claude` | Always Claude. No switching, no probe. |
| `ollama` | Always ollama. No switching, no probe. |
| unset | Automatic mode. |

**Automatic mode state machine:**

- Starts on Claude
- Tracks `consecutive_failures: int`; resets to 0 on success
- After `fallback_failure_threshold` consecutive failures: switch to ollama, publish Telegram notification
- Background probe runs every `fallback_probe_interval` seconds; checks availability by running `claude --version` (cheap, no API call)
- When probe succeeds while on ollama: publish Telegram notification ("Claude is back — reply /use-claude to switch")
- `/use-claude` slash command: switches back to Claude, resets failure count

**Notifications** are published onto the bus as outbound events to the user's Telegram chat.

### Slash Command

`/use-claude` added to the existing slash commands middleware. Only acts in automatic mode (unset `AWFULCLAW_FALLBACK`); silently ignored if `AWFULCLAW_FALLBACK` is set.

---

## Configuration

New `Settings` fields:

```python
ollama_url: str = "http://localhost:11434"
ollama_model: str = "llama3.2"
fallback_failure_threshold: int = 3
fallback_probe_interval: int = 600  # seconds, default 10 minutes
```

`AWFULCLAW_FALLBACK` is read directly from the environment at startup (not a `Settings` field) — it controls how components are wired, not runtime behaviour.

---

## Data Flow

```
Agent.reply()
    → BackendManager.complete()
        → [automatic mode] ClaudeClient.complete()   ← normal path
                           on failure: increment counter
                           at threshold: switch, notify
        → [automatic mode] OllamaClient.complete()   ← fallback path
                           MCPRunner: start servers, list tools
                           ollama /api/chat loop
                           MCPRunner: call tools, feed results back
```

---

## Error Handling

- `ClaudeClient` already retries 3 times before raising. `BackendManager` counts a failure after all retries are exhausted.
- `OllamaClient` raises if ollama is unreachable (no fallback from the fallback).
- `MCPRunner` raises if a tool call fails; `OllamaClient` propagates the error back to the user as a reply.

---

## Testing

Key test cases:

- `BackendManager` switches to ollama after N consecutive Claude failures
- `BackendManager` stays on Claude when `AWFULCLAW_FALLBACK=claude`
- `BackendManager` stays on ollama when `AWFULCLAW_FALLBACK=ollama`
- Probe detects Claude recovery and publishes Telegram notification
- `/use-claude` switches back only in automatic mode; no-op when `AWFULCLAW_FALLBACK` is set
- `OllamaClient` tool loop: zero tool calls, one round, multiple rounds
- `MCPRunner`: starts servers, lists tools, calls tools, tears down cleanly

Test infrastructure: existing pytest suite. Mock ollama HTTP with `aioresponses` or `respx`. Mock MCP servers with in-process stubs.

---

## Files Changed

| File | Change |
|---|---|
| `agent/llm_client.py` | New — `LLMClient` protocol |
| `agent/ollama_client.py` | New — `OllamaClient` |
| `agent/mcp_runner.py` | New — `MCPRunner` |
| `agent/backend_manager.py` | New — `BackendManager` |
| `agent/claude_client.py` | Minor — add protocol conformance annotation |
| `agent/agent.py` | Minor — typed against `LLMClient`, uses `BackendManager` |
| `agent/config.py` | Add 4 new `Settings` fields |
| `agent/middleware/slash_commands.py` | Add `/use-claude` handler |
| `agent/main.py` | Wire `BackendManager` based on `AWFULCLAW_FALLBACK` |
| `tests/` | New tests for all above |
