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
