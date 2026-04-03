"""Tests for OrientationHandler."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.handlers.orientation import OrientationHandler, _ORIENTATION_SENT_KEY


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.kv_get = AsyncMock(return_value=None)
    store.kv_set = AsyncMock()
    store.list_facts = AsyncMock(return_value=[])
    store.list_people = AsyncMock(return_value=[])
    store.list_schedules = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.invoke = AsyncMock(return_value="Hello! I'm online and ready.")
    return agent


@pytest.fixture
def mock_bus():
    bus = MagicMock()
    bus.post = AsyncMock()
    return bus


@pytest.fixture
def mcp_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps({"mcpServers": {"memory": {}, "schedule": {}}}))
    return cfg


def make_handler(mock_agent, mock_bus, mock_store, mcp_config):
    return OrientationHandler(mock_agent, mock_bus, mock_store, mcp_config)


@pytest.mark.asyncio
async def test_fires_on_first_start(mock_agent, mock_bus, mock_store, mcp_config):
    """Orientation invokes agent and sends message when flag is absent."""
    mock_store.kv_get = AsyncMock(side_effect=lambda key: {
        "last_channel": "chan1",
        "last_sender": "user1",
    }.get(key))

    handler = make_handler(mock_agent, mock_bus, mock_store, mcp_config)
    await handler.run()

    mock_agent.invoke.assert_called_once()
    mock_bus.post.assert_called_once()


@pytest.mark.asyncio
async def test_skips_on_subsequent_starts(mock_agent, mock_bus, mock_store, mcp_config):
    """Orientation does nothing when flag is already set."""
    mock_store.kv_get = AsyncMock(return_value="1")  # flag is set

    handler = make_handler(mock_agent, mock_bus, mock_store, mcp_config)
    await handler.run()

    mock_agent.invoke.assert_not_called()
    mock_bus.post.assert_not_called()


@pytest.mark.asyncio
async def test_sets_flag_after_sending(mock_agent, mock_bus, mock_store, mcp_config):
    """Orientation sets orientation_sent flag in kv after running."""
    mock_store.kv_get = AsyncMock(return_value=None)

    handler = make_handler(mock_agent, mock_bus, mock_store, mcp_config)
    await handler.run()

    mock_store.kv_set.assert_called_once_with(_ORIENTATION_SENT_KEY, "1")


@pytest.mark.asyncio
async def test_no_post_when_no_channel(mock_agent, mock_bus, mock_store, mcp_config):
    """Orientation does not post if last_channel/last_sender are not in kv."""
    mock_store.kv_get = AsyncMock(return_value=None)

    handler = make_handler(mock_agent, mock_bus, mock_store, mcp_config)
    await handler.run()

    mock_agent.invoke.assert_called_once()
    mock_bus.post.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_servers_included_in_prompt(mock_agent, mock_bus, mock_store, mcp_config):
    """Orientation prompt includes MCP server names."""
    mock_store.kv_get = AsyncMock(return_value=None)

    handler = make_handler(mock_agent, mock_bus, mock_store, mcp_config)
    await handler.run()

    prompt_arg = mock_agent.invoke.call_args[0][0]
    assert "memory" in prompt_arg
    assert "schedule" in prompt_arg


@pytest.mark.asyncio
async def test_missing_mcp_config_is_handled(mock_agent, mock_bus, mock_store, tmp_path):
    """Orientation does not crash if MCP config file is missing."""
    missing = tmp_path / "nonexistent.json"
    mock_store.kv_get = AsyncMock(return_value=None)

    handler = make_handler(mock_agent, mock_bus, mock_store, missing)
    await handler.run()

    mock_agent.invoke.assert_called_once()
    prompt_arg = mock_agent.invoke.call_args[0][0]
    assert "unavailable" in prompt_arg
