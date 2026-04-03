# Multi-Backend LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pluggable LLM backend system so the agent can fall back from Claude to a locally-running ollama model (with full MCP tool support) when Claude is unavailable, with automatic detection and manual recovery.

**Architecture:** Introduce a `LLMClient` protocol; `ClaudeClient` and `OllamaClient` both implement it. A `BackendManager` wraps both and handles switching logic. `OllamaClient` uses the existing `MCPClient` class (fresh instance per call) to orchestrate tool calls via a stdio + ollama chat loop. `Agent` is updated to hold a `LLMClient` (which `BackendManager` also satisfies).

**Tech Stack:** Python 3.12, httpx (already in deps), mcp SDK (already in deps), pytest + unittest.mock

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `agent/llm_client.py` | Create | `LLMClient` protocol with `complete()` + `health_check()` |
| `agent/ollama_client.py` | Create | HTTP chat loop with MCP tool orchestration |
| `agent/backend_manager.py` | Create | Generic primary/fallback switching, probe loop, notifications |
| `agent/claude_client.py` | Modify | Add `health_check()` method |
| `agent/agent.py` | Modify | Type annotation: `ClaudeClient` -> `LLMClient` |
| `agent/config.py` | Modify | Add 6 new Settings fields |
| `agent/middleware/slash.py` | Modify | Add `/use-primary` command |
| `agent/main.py` | Modify | Add `build_client()` factory, wire `BackendManager`, add probe task |
| `tests/test_llm_client.py` | Create | Protocol conformance tests |
| `tests/test_ollama_client.py` | Create | OllamaClient unit tests |
| `tests/test_backend_manager.py` | Create | BackendManager unit tests |
| `tests/test_middleware_slash.py` | Modify | Add `/use-primary` tests |
| `tests/test_main.py` | Modify | Add factory + wiring tests |

---

## Task 1: LLMClient Protocol

**Files:**
- Create: `agent/llm_client.py`
- Modify: `agent/claude_client.py`
- Modify: `agent/agent.py`
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_client.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.llm_client import LLMClient
from agent.claude_client import ClaudeClient


def test_claude_client_satisfies_protocol() -> None:
    client = ClaudeClient("claude-test")
    assert hasattr(client, "complete")
    assert hasattr(client, "health_check")
    assert asyncio.iscoroutinefunction(client.complete)
    assert asyncio.iscoroutinefunction(client.health_check)


async def test_claude_health_check_returns_true_when_binary_found() -> None:
    client = ClaudeClient("claude-test")
    proc = MagicMock()
    proc.returncode = 0
    proc.wait = AsyncMock()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await client.health_check()
    assert result is True


async def test_claude_health_check_returns_false_when_binary_missing() -> None:
    client = ClaudeClient("claude-test")
    with patch("shutil.which", return_value=None):
        result = await client.health_check()
    assert result is False


async def test_claude_health_check_returns_false_on_nonzero_exit() -> None:
    client = ClaudeClient("claude-test")
    proc = MagicMock()
    proc.returncode = 1
    proc.wait = AsyncMock()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await client.health_check()
    assert result is False
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_llm_client.py -v
```
Expected: `ImportError: cannot import name 'LLMClient' from 'agent.llm_client'`

- [ ] **Step 3: Create `agent/llm_client.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        mcp_config_path: Path,
        allowed_tools: list[str],
    ) -> str: ...

    async def health_check(self) -> bool: ...
```

- [ ] **Step 4: Add `health_check()` to `ClaudeClient`**

In `agent/claude_client.py`, add this method inside the `ClaudeClient` class after the `complete()` method:

```python
    async def health_check(self) -> bool:
        claude_bin = shutil.which("claude")
        if claude_bin is None:
            return False
        proc = await asyncio.create_subprocess_exec(
            claude_bin, "--version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
```

- [ ] **Step 5: Update `Agent` type annotation**

In `agent/agent.py`, replace:
```python
from agent.claude_client import ClaudeClient
```
with:
```python
from agent.llm_client import LLMClient
```

Change `__init__` signature from:
```python
    def __init__(self, client: ClaudeClient, settings: Settings, store: Store) -> None:
```
to:
```python
    def __init__(self, client: LLMClient, settings: Settings, store: Store) -> None:
```

- [ ] **Step 6: Run tests to verify pass**

```
uv run pytest tests/test_llm_client.py tests/test_claude_client.py tests/test_agent.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add agent/llm_client.py agent/claude_client.py agent/agent.py tests/test_llm_client.py
git commit -m "feat: add LLMClient protocol and health_check to ClaudeClient"
```

---

## Task 2: Config Updates

**Files:**
- Modify: `agent/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_config.py`:

```python
def test_new_backend_defaults() -> None:
    s = Settings()
    assert s.primary_backend == "claude"
    assert s.fallback_backend == "ollama"
    assert s.ollama_url == "http://localhost:11434"
    assert s.ollama_model == "llama3.2"
    assert s.fallback_failure_threshold == 3
    assert s.fallback_probe_interval == 600
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_config.py::test_new_backend_defaults -v
```
Expected: FAIL — `Settings` has no `primary_backend` attribute

- [ ] **Step 3: Add fields to `Settings` in `agent/config.py`**

Add these after the `obsidian_vault` field:

```python
    primary_backend: str = "claude"
    fallback_backend: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    fallback_failure_threshold: int = 3
    fallback_probe_interval: int = 600
```

- [ ] **Step 4: Run to verify pass**

```
uv run pytest tests/test_config.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add agent/config.py tests/test_config.py
git commit -m "feat: add multi-backend settings fields"
```

---

## Task 3: OllamaClient

**Files:**
- Create: `agent/ollama_client.py`
- Create: `tests/test_ollama_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ollama_client.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.ollama_client import OllamaClient


def _make_mcp_mock(tools: list[MagicMock] | None = None) -> MagicMock:
    mcp = MagicMock()
    mcp.connect_all = AsyncMock()
    mcp.disconnect_all = AsyncMock()
    mcp.list_tools = AsyncMock(return_value=tools or [])
    return mcp


@pytest.fixture
def config(tmp_path: Path) -> Path:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({
        "mcpServers": {"mem": {"command": "python", "args": ["-c", "pass"]}}
    }))
    return cfg


@patch("agent.ollama_client.MCPClient")
@patch("httpx.AsyncClient")
async def test_simple_response_no_tools(
    mock_http_class: MagicMock, mock_mcp_class: MagicMock, config: Path
) -> None:
    mock_mcp_class.return_value = _make_mcp_mock()

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"message": {"role": "assistant", "content": "Hello"}}
    http_instance = MagicMock()
    http_instance.post = AsyncMock(return_value=resp)
    mock_http_class.return_value.__aenter__ = AsyncMock(return_value=http_instance)
    mock_http_class.return_value.__aexit__ = AsyncMock(return_value=False)

    client = OllamaClient("http://localhost:11434", "llama3.2")
    result = await client.complete("Hi", "Be helpful", config, [])

    assert result == "Hello"
    mock_mcp_class.return_value.connect_all.assert_called_once()
    mock_mcp_class.return_value.disconnect_all.assert_called_once()


@patch("agent.ollama_client.MCPClient")
@patch("httpx.AsyncClient")
async def test_tool_call_one_round(
    mock_http_class: MagicMock, mock_mcp_class: MagicMock, config: Path
) -> None:
    """ollama returns a tool_call on first response, final text on second."""
    tool = MagicMock()
    tool.name = "memory_get"
    tool.description = "Get memory"
    tool.inputSchema = {"type": "object", "properties": {}}

    mcp = _make_mcp_mock(tools=[tool])
    tool_result = MagicMock()
    tool_result.content = [MagicMock(text="stored value")]
    mcp.call_tool = AsyncMock(return_value=tool_result)
    mock_mcp_class.return_value = mcp

    responses = [
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "memory_get", "arguments": {"key": "x"}}}],
            }
        },
        {"message": {"role": "assistant", "content": "The value is stored value"}},
    ]
    call_index = 0

    async def mock_post(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_index
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = responses[call_index]
        call_index += 1
        return r

    http_instance = MagicMock()
    http_instance.post = mock_post
    mock_http_class.return_value.__aenter__ = AsyncMock(return_value=http_instance)
    mock_http_class.return_value.__aexit__ = AsyncMock(return_value=False)

    client = OllamaClient("http://localhost:11434", "llama3.2")
    result = await client.complete("What is x?", "Be helpful", config, [])

    assert result == "The value is stored value"
    mcp.call_tool.assert_called_once_with("memory_get", {"key": "x"})


async def test_health_check_ok() -> None:
    client = OllamaClient("http://localhost:11434", "llama3.2")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    http_instance = MagicMock()
    http_instance.get = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient") as mock_http_class:
        mock_http_class.return_value.__aenter__ = AsyncMock(return_value=http_instance)
        mock_http_class.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await client.health_check()
    assert result is True


async def test_health_check_connection_error() -> None:
    client = OllamaClient("http://localhost:11434", "llama3.2")
    http_instance = MagicMock()
    http_instance.get = AsyncMock(side_effect=Exception("connection refused"))
    with patch("httpx.AsyncClient") as mock_http_class:
        mock_http_class.return_value.__aenter__ = AsyncMock(return_value=http_instance)
        mock_http_class.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await client.health_check()
    assert result is False


@patch("agent.ollama_client.MCPClient")
@patch("httpx.AsyncClient")
async def test_disconnect_called_even_on_error(
    mock_http_class: MagicMock, mock_mcp_class: MagicMock, config: Path
) -> None:
    """MCPClient.disconnect_all must run even if the HTTP call raises."""
    mcp = _make_mcp_mock()
    mock_mcp_class.return_value = mcp

    http_instance = MagicMock()
    http_instance.post = AsyncMock(side_effect=RuntimeError("ollama down"))
    mock_http_class.return_value.__aenter__ = AsyncMock(return_value=http_instance)
    mock_http_class.return_value.__aexit__ = AsyncMock(return_value=False)

    client = OllamaClient("http://localhost:11434", "llama3.2")
    with pytest.raises(RuntimeError, match="ollama down"):
        await client.complete("hi", "sys", config, [])

    mcp.disconnect_all.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_ollama_client.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent.ollama_client'`

- [ ] **Step 3: Create `agent/ollama_client.py`**

```python
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import httpx

from agent.mcp import MCPClient


class OllamaClient:
    def __init__(self, url: str, model: str) -> None:
        self._url = url.rstrip("/")
        self._model = model

    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        mcp_config_path: Path,
        allowed_tools: list[str],
    ) -> str:
        # Filter to stdio-only servers (mirrors ClaudeClient behaviour)
        raw = json.loads(mcp_config_path.read_text())
        servers = raw.get("mcpServers", raw)
        stdio_servers = {k: v for k, v in servers.items() if "command" in v}
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=mcp_config_path.parent
        )
        json.dump({"mcpServers": stdio_servers}, tmp)
        tmp.flush()
        effective_config = Path(tmp.name)

        mcp = MCPClient()
        try:
            await mcp.connect_all(effective_config)
            tools = await mcp.list_tools()
            ollama_tools = [_tool_to_ollama(t) for t in tools]

            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            async with httpx.AsyncClient(timeout=120.0) as http:
                while True:
                    resp = await http.post(
                        f"{self._url}/api/chat",
                        json={
                            "model": self._model,
                            "messages": messages,
                            "tools": ollama_tools,
                            "stream": False,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data["message"]
                    tool_calls = msg.get("tool_calls")

                    if not tool_calls:
                        return msg.get("content", "")

                    messages.append({
                        "role": "assistant",
                        "content": msg.get("content", ""),
                        "tool_calls": tool_calls,
                    })
                    for tc in tool_calls:
                        fn = tc["function"]
                        result = await mcp.call_tool(fn["name"], fn.get("arguments") or {})
                        messages.append({
                            "role": "tool",
                            "content": _extract_content(result),
                        })
        finally:
            await mcp.disconnect_all()
            effective_config.unlink(missing_ok=True)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(f"{self._url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False


def _tool_to_ollama(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


def _extract_content(result: Any) -> str:
    parts: list[str] = []
    for item in result.content:
        if hasattr(item, "text"):
            parts.append(item.text)
        else:
            parts.append(str(item))
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify pass**

```
uv run pytest tests/test_ollama_client.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add agent/ollama_client.py tests/test_ollama_client.py
git commit -m "feat: add OllamaClient with MCP tool loop"
```

---

## Task 4: BackendManager

**Files:**
- Create: `agent/backend_manager.py`
- Create: `tests/test_backend_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backend_manager.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.backend_manager import BackendManager
from agent.connectors import OutboundEvent

MCP_CONFIG = Path("/tmp/mcp.json")


def _make_client(*, fail: bool = False, response: str = "ok") -> MagicMock:
    client = MagicMock()
    if fail:
        client.complete = AsyncMock(side_effect=RuntimeError("backend error"))
    else:
        client.complete = AsyncMock(return_value=response)
    client.health_check = AsyncMock(return_value=not fail)
    return client


def _make_manager(
    primary: MagicMock,
    fallback: MagicMock | None = None,
    *,
    threshold: int = 3,
    locked: bool = False,
    bus: MagicMock | None = None,
    notify_channel: tuple[str, str] | None = None,
) -> BackendManager:
    return BackendManager(
        primary=primary,
        fallback=fallback,
        failure_threshold=threshold,
        probe_interval=1,
        bus=bus,
        notify_channel=notify_channel,
        locked=locked,
    )


async def test_passes_through_to_primary() -> None:
    primary = _make_client(response="from primary")
    mgr = _make_manager(primary)
    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "from primary"
    primary.complete.assert_called_once()


async def test_resets_failure_count_on_primary_success() -> None:
    primary = _make_client()
    fallback = _make_client()
    mgr = _make_manager(primary, fallback, threshold=3)
    # two failures then a success — should never switch
    primary.complete = AsyncMock(side_effect=[
        RuntimeError("err"), RuntimeError("err"), "ok"
    ])
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "ok"
    fallback.complete.assert_not_called()


async def test_switches_to_fallback_after_threshold() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="from fallback")
    bus = MagicMock()
    bus.post = AsyncMock()
    mgr = _make_manager(
        primary, fallback, threshold=2, bus=bus, notify_channel=("telegram", "123")
    )

    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    fallback.complete.assert_not_called()

    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "from fallback"
    fallback.complete.assert_called_once()
    bus.post.assert_called_once()
    event: OutboundEvent = bus.post.call_args[0][0]
    assert "Ollama" in event.message.text


async def test_locked_never_switches() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="should not be called")
    mgr = _make_manager(primary, fallback, threshold=1, locked=True)

    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    fallback.complete.assert_not_called()


async def test_switch_to_primary_in_automatic_mode() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="fallback")
    mgr = _make_manager(primary, fallback, threshold=1)

    await mgr.complete("q", "sys", MCP_CONFIG, [])  # triggers switch

    primary.complete = AsyncMock(return_value="primary restored")
    await mgr.switch_to_primary()
    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "primary restored"


async def test_switch_to_primary_is_noop_when_locked() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="fallback")
    mgr = _make_manager(primary, fallback, threshold=1, locked=True)

    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    await mgr.switch_to_primary()  # no-op
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    fallback.complete.assert_not_called()


async def test_check_and_notify_sends_recovery_message() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="fallback")
    bus = MagicMock()
    bus.post = AsyncMock()
    mgr = _make_manager(
        primary, fallback, threshold=1, bus=bus, notify_channel=("telegram", "123")
    )

    await mgr.complete("q", "sys", MCP_CONFIG, [])  # triggers switch; post called once

    primary.health_check = AsyncMock(return_value=True)
    await mgr._check_and_notify()

    assert bus.post.call_count == 2
    recovery_event: OutboundEvent = bus.post.call_args[0][0]
    assert "/use-primary" in recovery_event.message.text


async def test_check_and_notify_silent_when_not_on_fallback() -> None:
    primary = _make_client()
    fallback = _make_client()
    bus = MagicMock()
    bus.post = AsyncMock()
    mgr = _make_manager(primary, fallback, bus=bus, notify_channel=("telegram", "123"))

    await mgr._check_and_notify()
    bus.post.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_backend_manager.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent.backend_manager'`

- [ ] **Step 3: Create `agent/backend_manager.py`**

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from agent.bus import Bus
from agent.connectors import OutboundEvent, OutboundMessage
from agent.llm_client import LLMClient


class BackendManager:
    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient | None,
        failure_threshold: int,
        probe_interval: int,
        bus: Bus | None = None,
        notify_channel: tuple[str, str] | None = None,
        locked: bool = False,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._threshold = failure_threshold
        self._probe_interval = probe_interval
        self._bus = bus
        self._notify_channel = notify_channel
        self._locked = locked
        self._active: LLMClient = primary
        self._failures = 0
        self._on_fallback = False

    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        mcp_config_path: Path,
        allowed_tools: list[str],
    ) -> str:
        try:
            result = await self._active.complete(
                prompt, system_prompt, mcp_config_path, allowed_tools
            )
            if not self._locked and not self._on_fallback:
                self._failures = 0
            return result
        except Exception:
            if self._locked or self._fallback is None or self._on_fallback:
                raise
            self._failures += 1
            if self._failures >= self._threshold:
                await self._switch_to_fallback()
                return await self._active.complete(
                    prompt, system_prompt, mcp_config_path, allowed_tools
                )
            raise

    async def health_check(self) -> bool:
        return await self._active.health_check()

    async def switch_to_primary(self) -> None:
        """Called by /use-primary. No-op when locked."""
        if self._locked:
            return
        self._active = self._primary
        self._on_fallback = False
        self._failures = 0
        await self._notify("Switched back to Claude. I'm fully operational again.")

    async def probe_loop(self) -> None:
        """Background asyncio task: probe primary backend and notify on recovery."""
        while True:
            await asyncio.sleep(self._probe_interval)
            await self._check_and_notify()

    async def _check_and_notify(self) -> None:
        if self._locked or not self._on_fallback:
            return
        try:
            ok = await self._primary.health_check()
        except Exception:
            ok = False
        if ok:
            await self._notify(
                "Claude CLI is back. Reply /use-primary to switch back."
            )

    async def _switch_to_fallback(self) -> None:
        self._active = self._fallback  # type: ignore[assignment]
        self._on_fallback = True
        self._failures = 0
        await self._notify(
            "Claude CLI is unavailable. Switched to local Ollama model — "
            "memory and tools are available but responses will be slower "
            "and less accurate."
        )

    async def _notify(self, text: str) -> None:
        if self._bus is None or self._notify_channel is None:
            return
        connector_name, channel = self._notify_channel
        await self._bus.post(
            OutboundEvent(
                channel=channel,
                to=channel,
                message=OutboundMessage(text=text),
                connector_name=connector_name,
            )
        )
```

- [ ] **Step 4: Run tests to verify pass**

```
uv run pytest tests/test_backend_manager.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add agent/backend_manager.py tests/test_backend_manager.py
git commit -m "feat: add BackendManager with automatic fallback and probe loop"
```

---

## Task 5: /use-primary Slash Command

**Files:**
- Modify: `agent/middleware/slash.py`
- Modify: `tests/test_middleware_slash.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/test_middleware_slash.py`:

```python
from agent.backend_manager import BackendManager


@pytest.mark.asyncio
async def test_use_primary_calls_backend_manager() -> None:
    connector = MagicMock()
    connector.send = AsyncMock()
    store = MagicMock()
    store.list_schedules = AsyncMock(return_value=[])
    backend = MagicMock(spec=BackendManager)
    backend.switch_to_primary = AsyncMock()
    mw = SlashCommandMiddleware(
        connectors={"test": connector}, store=store, backend_manager=backend
    )

    await mw(make_event("/use-primary"), AsyncMock())

    backend.switch_to_primary.assert_called_once()
    connector.send.assert_called_once()


@pytest.mark.asyncio
async def test_use_primary_no_backend_manager_does_not_raise() -> None:
    connector = MagicMock()
    connector.send = AsyncMock()
    store = MagicMock()
    store.list_schedules = AsyncMock(return_value=[])
    mw = SlashCommandMiddleware(connectors={"test": connector}, store=store)
    next_fn: Next = AsyncMock()

    await mw(make_event("/use-primary"), next_fn)

    next_fn.assert_not_called()
    connector.send.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_middleware_slash.py::test_use_primary_calls_backend_manager tests/test_middleware_slash.py::test_use_primary_no_backend_manager_does_not_raise -v
```
Expected: FAIL — `SlashCommandMiddleware.__init__` does not accept `backend_manager`

- [ ] **Step 3: Update `agent/middleware/slash.py`**

Replace the entire file content:

```python
from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable
from typing import TYPE_CHECKING

from agent.connectors import Connector, InboundEvent, OutboundMessage
from agent.middleware import Next
from agent.store import Store

if TYPE_CHECKING:
    from agent.backend_manager import BackendManager


class SlashCommandMiddleware:
    def __init__(
        self,
        connectors: dict[str, Connector],
        store: Store,
        restart_fn: Callable[[], None] | None = None,
        backend_manager: "BackendManager | None" = None,
    ) -> None:
        self._connectors = connectors
        self._store = store
        self._restart_fn = restart_fn or (lambda: os.kill(os.getpid(), signal.SIGTERM))
        self._backend_manager = backend_manager

    async def __call__(self, event: InboundEvent, next: Next) -> None:
        text = event.message.text.strip()

        if not text.startswith("/"):
            await next(event)
            return

        command = text.split()[0].lower()

        if command == "/schedules":
            schedules = await self._store.list_schedules()
            if schedules:
                lines = [f"- {s.name} ({s.cron or s.fire_at or 'no time'})" for s in schedules]
                reply = "Schedules:\n" + "\n".join(lines)
            else:
                reply = "No schedules."
            c = self._connectors.get(event.connector_name)
            if c:
                await c.send(event.channel, OutboundMessage(text=reply))
            return

        if command == "/restart":
            c = self._connectors.get(event.connector_name)
            if c:
                await c.send(event.channel, OutboundMessage(text="Restarting..."))
            asyncio.get_running_loop().call_later(0.1, self._restart_fn)
            return

        if command == "/use-primary":
            if self._backend_manager is not None:
                await self._backend_manager.switch_to_primary()
            c = self._connectors.get(event.connector_name)
            if c:
                await c.send(event.channel, OutboundMessage(text="Switching to primary backend..."))
            return

        # Unknown slash command — pass through to the agent
        await next(event)
```

- [ ] **Step 4: Run tests to verify pass**

```
uv run pytest tests/test_middleware_slash.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add agent/middleware/slash.py tests/test_middleware_slash.py
git commit -m "feat: add /use-primary slash command"
```

---

## Task 6: Wire main.py

**Files:**
- Modify: `agent/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main.py`:

```python
import pytest
from agent.main import build_client
from agent.config import Settings
from agent.claude_client import ClaudeClient
from agent.ollama_client import OllamaClient


def test_build_client_returns_claude() -> None:
    client = build_client("claude", Settings())
    assert isinstance(client, ClaudeClient)


def test_build_client_returns_ollama() -> None:
    client = build_client("ollama", Settings())
    assert isinstance(client, OllamaClient)


def test_build_client_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown backend"):
        build_client("gemini", Settings())
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_main.py::test_build_client_returns_claude tests/test_main.py::test_build_client_returns_ollama tests/test_main.py::test_build_client_unknown_raises -v
```
Expected: FAIL — `cannot import name 'build_client' from 'agent.main'`

- [ ] **Step 3: Add imports and `build_client()` to `agent/main.py`**

Add these imports after the existing import block in `agent/main.py`:

```python
import os

from agent.backend_manager import BackendManager
from agent.llm_client import LLMClient
from agent.ollama_client import OllamaClient
```

Add this function immediately before `async def preflight(...)`:

```python
def build_client(name: str, settings: Settings) -> LLMClient:
    match name:
        case "claude":
            return ClaudeClient(settings.model)
        case "ollama":
            return OllamaClient(settings.ollama_url, settings.ollama_model)
        case _:
            raise ValueError(f"Unknown backend: {name!r}")
```

- [ ] **Step 4: Run factory tests to verify pass**

```
uv run pytest tests/test_main.py::test_build_client_returns_claude tests/test_main.py::test_build_client_returns_ollama tests/test_main.py::test_build_client_unknown_raises -v
```
Expected: all PASS

- [ ] **Step 5: Replace ClaudeClient wiring in `main()` with BackendManager**

In `agent/main.py`, inside `async def main()`, find:

```python
        client = ClaudeClient(settings.model)
        agent = Agent(client, settings, store)
```

Replace with:

```python
        forced_backend = os.environ.get("AWFULCLAW_BACKEND")
        notify_channel: tuple[str, str] | None = None
        if settings.telegram and settings.telegram.allowed_chat_ids:
            notify_channel = ("telegram", str(settings.telegram.allowed_chat_ids[0]))

        if forced_backend:
            backend = BackendManager(
                primary=build_client(forced_backend, settings),
                fallback=None,
                failure_threshold=settings.fallback_failure_threshold,
                probe_interval=settings.fallback_probe_interval,
                locked=True,
            )
        else:
            backend = BackendManager(
                primary=build_client(settings.primary_backend, settings),
                fallback=build_client(settings.fallback_backend, settings),
                failure_threshold=settings.fallback_failure_threshold,
                probe_interval=settings.fallback_probe_interval,
                bus=bus,
                notify_channel=notify_channel,
            )

        agent = Agent(backend, settings, store)
```

- [ ] **Step 6: Pass `backend_manager` to `SlashCommandMiddleware`**

Find in `agent/main.py`:

```python
            SlashCommandMiddleware(connectors, store),
```

Replace with:

```python
            SlashCommandMiddleware(connectors, store, backend_manager=backend),
```

- [ ] **Step 7: Add probe task**

Inside the `async with asyncio.TaskGroup() as tg:` block, add this line alongside the other `tg.create_task(...)` calls:

```python
                tg.create_task(backend.probe_loop())
```

- [ ] **Step 8: Run full test suite**

```
uv run pytest -v
```
Expected: all PASS (test_live_agent.py is always excluded by pytest config)

- [ ] **Step 9: Commit**

```bash
git add agent/main.py tests/test_main.py
git commit -m "feat: wire BackendManager into main with build_client factory"
```

---

## Task 7: Verify Governance Model Isolation

The `governance_model` setting is used for policy decisions and should stay on a direct `ClaudeClient`, not go through `BackendManager`.

- [ ] **Step 1: Check how governance_model is used**

```bash
grep -rn "governance_model" agent/
```

Look for any place a `ClaudeClient(settings.governance_model)` is instantiated. If it is already a separate direct instantiation (not through the new `backend` variable), no changes are needed.

- [ ] **Step 2: Run full test suite**

```
uv run pytest -v
```
Expected: all PASS

- [ ] **Step 3: Commit if any changes were needed**

```bash
git add agent/
git commit -m "fix: ensure governance_model stays on dedicated ClaudeClient"
```

Skip this step if grep showed no governance_model usage in agent code, or if it was already isolated.
