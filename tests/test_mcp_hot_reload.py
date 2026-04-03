from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.mcp import MCPClient


def _write_config(path: Path, servers: dict) -> None:
    path.write_text(json.dumps(servers))


def _make_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


def _make_session(tools: list[MagicMock]) -> AsyncMock:
    session = AsyncMock()
    list_result = MagicMock()
    list_result.tools = tools
    session.list_tools = AsyncMock(return_value=list_result)
    session.initialize = AsyncMock()
    return session


def _make_stdio_cm() -> MagicMock:
    read, write = MagicMock(), MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=(read, write))
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_session_cm(session: AsyncMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


async def test_reload_if_changed_detects_no_change() -> None:
    """reload_if_changed does nothing when mtime is unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mcp.json"
        _write_config(cfg, {"srv": {"command": "x"}})

        session = _make_session([_make_tool("t")])
        with (
            patch("agent.mcp.stdio_client", return_value=_make_stdio_cm()),
            patch("agent.mcp.ClientSession", return_value=_make_session_cm(session)),
        ):
            client = MCPClient()
            await client.connect_all(cfg)

            initial_sessions = len(client._sessions)
            await client.reload_if_changed()

            # Nothing changed — sessions unchanged
            assert len(client._sessions) == initial_sessions
            await client.disconnect_all()


async def test_reload_if_changed_adds_new_server() -> None:
    """reload_if_changed connects a new server when one is added to config."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mcp.json"
        _write_config(cfg, {"srv1": {"command": "x"}})

        session1 = _make_session([_make_tool("tool_one")])
        session2 = _make_session([_make_tool("tool_two")])

        stdio_effects = [_make_stdio_cm(), _make_stdio_cm()]
        session_effects = [_make_session_cm(session1), _make_session_cm(session2)]

        with (
            patch("agent.mcp.stdio_client", side_effect=stdio_effects),
            patch("agent.mcp.ClientSession", side_effect=session_effects),
        ):
            client = MCPClient()
            await client.connect_all(cfg)
            assert "tool_one" in client._tool_map
            assert "tool_two" not in client._tool_map

            # Modify config to add srv2, bump mtime by writing again
            _write_config(cfg, {"srv1": {"command": "x"}, "srv2": {"command": "y"}})
            # Force mtime difference by manipulating tracked mtime
            client._config_mtime = 0.0

            await client.reload_if_changed()

            assert "tool_two" in client._tool_map
            assert len(client._sessions) == 2
            await client.disconnect_all()


async def test_reload_if_changed_removes_old_server() -> None:
    """reload_if_changed disconnects a server removed from config."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mcp.json"
        _write_config(cfg, {"srv1": {"command": "x"}, "srv2": {"command": "y"}})

        session1 = _make_session([_make_tool("tool_one")])
        session2 = _make_session([_make_tool("tool_two")])

        stdio_effects = [_make_stdio_cm(), _make_stdio_cm()]
        session_effects = [_make_session_cm(session1), _make_session_cm(session2)]

        with (
            patch("agent.mcp.stdio_client", side_effect=stdio_effects),
            patch("agent.mcp.ClientSession", side_effect=session_effects),
        ):
            client = MCPClient()
            await client.connect_all(cfg)
            assert "tool_one" in client._tool_map
            assert "tool_two" in client._tool_map
            assert len(client._sessions) == 2

            # Remove srv2 from config
            _write_config(cfg, {"srv1": {"command": "x"}})
            client._config_mtime = 0.0

            await client.reload_if_changed()

            assert "tool_one" in client._tool_map
            assert "tool_two" not in client._tool_map
            assert len(client._sessions) == 1
            assert "srv2" not in client._server_sessions
            await client.disconnect_all()


async def test_watch_config_calls_reload_on_interval() -> None:
    """watch_config calls reload_if_changed after each interval."""
    client = MCPClient()
    reload_calls: list[None] = []

    async def fake_reload() -> None:
        reload_calls.append(None)

    client.reload_if_changed = fake_reload  # type: ignore[method-assign]

    with patch("asyncio.sleep", new=AsyncMock(side_effect=[None, None, asyncio.CancelledError()])):
        with pytest.raises(asyncio.CancelledError):
            await client.watch_config(Path("/fake/mcp.json"), interval=5.0)

    assert len(reload_calls) == 2


async def test_reload_if_changed_no_config_path() -> None:
    """reload_if_changed is a no-op when no config path has been set."""
    client = MCPClient()
    # Should not raise
    await client.reload_if_changed()
    assert client._sessions == []
