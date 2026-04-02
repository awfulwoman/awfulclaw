from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.claude_client import ClaudeClient


def _make_stream_json(*events: dict) -> bytes:
    return "\n".join(json.dumps(e) for e in events).encode()


def _mock_proc(returncode: int, stdout: bytes, stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


STREAM_OK = _make_stream_json(
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "4"}]}},
    {"type": "result", "result": "4"},
)

MCP_CONFIG = Path("/tmp/mcp.json")


@pytest.fixture
def client() -> ClaudeClient:
    return ClaudeClient(model="claude-test")


async def test_successful_parse(client: ClaudeClient) -> None:
    proc = _mock_proc(0, STREAM_OK)
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await client.complete("2+2", "sys", MCP_CONFIG, [])
    assert result == "4"


async def test_prompt_passed_via_stdin(client: ClaudeClient) -> None:
    proc = _mock_proc(0, STREAM_OK)
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await client.complete("hello", "sys", MCP_CONFIG, [])

    _, communicate_args, _ = proc.communicate.mock_calls[0]
    assert communicate_args[0] == b"sys\n\nhello"


async def test_retry_on_failure(client: ClaudeClient) -> None:
    fail_proc = _mock_proc(1, b"", b"error")
    ok_proc = _mock_proc(0, STREAM_OK)

    call_count = 0

    async def fake_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return fail_proc if call_count < 3 else ok_proc

    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("asyncio.create_subprocess_exec", fake_exec), \
         patch("asyncio.sleep", AsyncMock()):
        result = await client.complete("2+2", "sys", MCP_CONFIG, [])

    assert result == "4"
    assert call_count == 3


async def test_raises_after_three_failures(client: ClaudeClient) -> None:
    fail_proc = _mock_proc(1, b"", b"rate limit")

    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fail_proc)), \
         patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(RuntimeError, match="3 attempts"):
            await client.complete("2+2", "sys", MCP_CONFIG, [])


async def test_missing_claude_binary(client: ClaudeClient) -> None:
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="claude CLI not found"):
            await client.complete("2+2", "sys", MCP_CONFIG, [])


async def test_allowed_tools_passed(client: ClaudeClient) -> None:
    proc = _mock_proc(0, STREAM_OK)
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await client.complete("q", "sys", MCP_CONFIG, ["WebSearch", "WebFetch"])

    cmd = mock_exec.call_args[0]
    idx = list(cmd).index("--allowedTools")
    assert cmd[idx + 1] == "WebSearch,WebFetch"
