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
