from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.agent import Agent, _format_history
from agent.connectors import InboundEvent, Message
from agent.store import Turn


def _fake_embed(text: str) -> bytes:
    return struct.pack(f"{384}f", *([0.1] * 384))


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.complete = AsyncMock(return_value="hello back")
    return client


@pytest.fixture
def mock_settings(tmp_path: Path) -> MagicMock:
    cfg = tmp_path / "agent_config"
    cfg.mkdir()
    (cfg / "PERSONALITY.md").write_text("I am Ralph.")
    (cfg / "PROTOCOLS.md").write_text("Be concise.")
    (cfg / "USER.md").write_text("User is Charlie.")
    mcp = tmp_path / "mcp.json"
    mcp.write_text("{}")
    s = MagicMock()
    s.agent_config_path = cfg
    s.mcp_config = mcp
    s.model = "claude-sonnet-4-6"
    return s


@pytest.fixture
def mock_store() -> AsyncMock:
    store = AsyncMock()
    store.add_turn = AsyncMock(return_value=Turn(id=1, channel="tg", role="user", content="hi", timestamp="2026-01-01"))
    store.recent_turns = AsyncMock(return_value=[
        Turn(id=1, channel="tg", role="user", content="hi", timestamp="2026-01-01"),
    ])
    store.list_schedules = AsyncMock(return_value=[])
    store.list_personality_log = AsyncMock(return_value=[])
    store.search_facts = AsyncMock(return_value=[])
    store.search_people = AsyncMock(return_value=[])
    return store


def _make_event(text: str = "hello", channel: str = "tg") -> InboundEvent:
    return InboundEvent(
        channel=channel,
        message=Message(text=text, sender="123", sender_name="Charlie"),
        connector_name="telegram",
    )


@pytest.mark.asyncio
@patch("agent.store.embed", side_effect=_fake_embed)
async def test_reply_stores_turns(mock_embed: MagicMock, mock_client: AsyncMock, mock_settings: MagicMock, mock_store: AsyncMock) -> None:
    agent = Agent(mock_client, mock_settings, mock_store)
    event = _make_event("hello")

    result = await agent.reply(event)

    assert result == "hello back"
    # user turn stored
    mock_store.add_turn.assert_any_call("tg", "user", "hello")
    # assistant turn stored
    mock_store.add_turn.assert_any_call("tg", "assistant", "hello back")


@pytest.mark.asyncio
@patch("agent.store.embed", side_effect=_fake_embed)
async def test_reply_uses_system_prompt(mock_embed: MagicMock, mock_client: AsyncMock, mock_settings: MagicMock, mock_store: AsyncMock) -> None:
    agent = Agent(mock_client, mock_settings, mock_store)
    await agent.reply(_make_event("hi"))

    call_kwargs = mock_client.complete.call_args
    system_prompt = call_kwargs.kwargs.get("system_prompt") or call_kwargs.args[1]
    assert "Ralph" in system_prompt or "Identity" in system_prompt


@pytest.mark.asyncio
@patch("agent.store.embed", side_effect=_fake_embed)
async def test_reply_passes_history(mock_embed: MagicMock, mock_client: AsyncMock, mock_settings: MagicMock, mock_store: AsyncMock) -> None:
    mock_store.recent_turns = AsyncMock(return_value=[
        Turn(id=1, channel="tg", role="user", content="first message", timestamp="2026-01-01"),
        Turn(id=2, channel="tg", role="assistant", content="first reply", timestamp="2026-01-02"),
        Turn(id=3, channel="tg", role="user", content="second message", timestamp="2026-01-03"),
    ])
    agent = Agent(mock_client, mock_settings, mock_store)
    await agent.reply(_make_event("second message"))

    call_kwargs = mock_client.complete.call_args
    prompt = call_kwargs.kwargs.get("prompt") or call_kwargs.args[0]
    assert "first message" in prompt
    assert "first reply" in prompt


@pytest.mark.asyncio
@patch("agent.store.embed", side_effect=_fake_embed)
async def test_invoke_uses_assembler(mock_embed: MagicMock, mock_client: AsyncMock, mock_settings: MagicMock, mock_store: AsyncMock) -> None:
    agent = Agent(mock_client, mock_settings, mock_store)
    result = await agent.invoke("run daily briefing")

    assert result == "hello back"
    call_kwargs = mock_client.complete.call_args
    system_prompt = call_kwargs.kwargs.get("system_prompt") or call_kwargs.args[1]
    assert len(system_prompt) > 0


def test_format_history_empty() -> None:
    assert _format_history([]) == ""


def test_format_history_formats_roles() -> None:
    turns = [
        Turn(id=1, channel="c", role="user", content="hello", timestamp="t"),
        Turn(id=2, channel="c", role="assistant", content="hi", timestamp="t"),
    ]
    result = _format_history(turns)
    assert "user: hello" in result
    assert "assistant: hi" in result
