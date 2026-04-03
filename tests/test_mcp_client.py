from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.mcp import MCPClient


def _make_config(servers: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(servers, tmp)
    tmp.close()
    return Path(tmp.name)


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


def _patch_stdio(session: AsyncMock):
    """Return a context manager that yields (read, write) + patches ClientSession."""
    read, write = MagicMock(), MagicMock()

    # stdio_client context manager yields (read, write)
    stdio_cm = MagicMock()
    stdio_cm.__aenter__ = AsyncMock(return_value=(read, write))
    stdio_cm.__aexit__ = AsyncMock(return_value=False)

    # ClientSession context manager yields session
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    return stdio_cm, session_cm


async def test_config_parsing_command_and_args() -> None:
    """connect_all reads command, args, and env from the JSON config."""
    cfg = _make_config(
        {"demo": {"command": "echo", "args": ["-n", "hi"], "env": {"FOO": "bar"}}}
    )
    session = _make_session([])
    stdio_cm, session_cm = _patch_stdio(session)

    with (
        patch("agent.mcp.stdio_client", return_value=stdio_cm) as mock_stdio,
        patch("agent.mcp.ClientSession", return_value=session_cm),
    ):
        client = MCPClient()
        await client.connect_all(cfg)
        await client.disconnect_all()

    call_kwargs = mock_stdio.call_args[0][0]
    assert call_kwargs.command == "echo"
    assert call_kwargs.args == ["-n", "hi"]
    assert call_kwargs.env == {"FOO": "bar"}


async def test_config_parsing_defaults() -> None:
    """args defaults to [] and env defaults to None when omitted."""
    cfg = _make_config({"minimal": {"command": "cat"}})
    session = _make_session([])
    stdio_cm, session_cm = _patch_stdio(session)

    with (
        patch("agent.mcp.stdio_client", return_value=stdio_cm) as mock_stdio,
        patch("agent.mcp.ClientSession", return_value=session_cm),
    ):
        client = MCPClient()
        await client.connect_all(cfg)
        await client.disconnect_all()

    call_kwargs = mock_stdio.call_args[0][0]
    assert call_kwargs.args == []
    assert call_kwargs.env is None


async def test_list_tools_combined() -> None:
    """list_tools returns tools from all connected servers."""
    tool_a = _make_tool("tool_a")
    tool_b = _make_tool("tool_b")

    # Two servers, one tool each
    cfg = _make_config(
        {
            "srv1": {"command": "a"},
            "srv2": {"command": "b"},
        }
    )

    session1 = _make_session([tool_a])
    session2 = _make_session([tool_b])
    sessions = [session1, session2]

    call_count = 0

    def _make_stdio_cm():
        nonlocal call_count
        read, write = MagicMock(), MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=(read, write))
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    def _make_session_cm(idx: int):
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=sessions[idx])
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    stdio_side_effects = [_make_stdio_cm(), _make_stdio_cm()]
    session_side_effects = [_make_session_cm(0), _make_session_cm(1)]

    with (
        patch("agent.mcp.stdio_client", side_effect=stdio_side_effects),
        patch("agent.mcp.ClientSession", side_effect=session_side_effects),
    ):
        client = MCPClient()
        await client.connect_all(cfg)
        tools = await client.list_tools()
        await client.disconnect_all()

    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"tool_a", "tool_b"}


async def test_call_tool_dispatches_to_correct_session() -> None:
    """call_tool routes to the session that owns the tool."""
    tool_a = _make_tool("greet")
    cfg = _make_config({"srv": {"command": "x"}})
    session = _make_session([tool_a])
    stdio_cm, session_cm = _patch_stdio(session)

    expected_result = MagicMock()
    session.call_tool = AsyncMock(return_value=expected_result)

    with (
        patch("agent.mcp.stdio_client", return_value=stdio_cm),
        patch("agent.mcp.ClientSession", return_value=session_cm),
    ):
        client = MCPClient()
        await client.connect_all(cfg)
        result = await client.call_tool("greet", {"name": "world"})
        await client.disconnect_all()

    session.call_tool.assert_called_once_with("greet", {"name": "world"})
    assert result is expected_result


async def test_call_tool_unknown_raises_key_error() -> None:
    """call_tool raises KeyError for tools not registered by any server."""
    client = MCPClient()
    with pytest.raises(KeyError, match="unknown"):
        await client.call_tool("unknown", {})


async def test_disconnect_clears_state() -> None:
    """disconnect_all resets sessions and tool_map."""
    tool = _make_tool("t")
    cfg = _make_config({"srv": {"command": "x"}})
    session = _make_session([tool])
    stdio_cm, session_cm = _patch_stdio(session)

    with (
        patch("agent.mcp.stdio_client", return_value=stdio_cm),
        patch("agent.mcp.ClientSession", return_value=session_cm),
    ):
        client = MCPClient()
        await client.connect_all(cfg)
        assert len(client._sessions) == 1
        await client.disconnect_all()

    assert client._sessions == []
    assert client._tool_map == {}
