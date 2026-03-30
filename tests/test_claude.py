"""Tests for claude.py CLI invocation."""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

from awfulclaw import claude


def _make_completed_process(stdout: str = "hello", returncode: int = 0):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = ""
    result.returncode = returncode
    return result


def test_chat_cli_basic():
    """Basic chat call builds a subprocess command."""
    with patch("subprocess.run", return_value=_make_completed_process("hi")) as mock_run:
        reply = claude.chat([{"role": "user", "content": "hello"}], system="sys")
    assert reply == "hi"
    cmd = mock_run.call_args[0][0]
    assert "claude" in cmd
    assert "--print" in cmd
    assert "--no-session-persistence" in cmd


def test_chat_cli_no_mcp_config_by_default():
    """--mcp-config is not added when mcp_config_path is None."""
    with patch("subprocess.run", return_value=_make_completed_process("ok")) as mock_run:
        claude.chat([{"role": "user", "content": "hi"}], system="sys")
    cmd = mock_run.call_args[0][0]
    assert "--mcp-config" not in cmd


def test_chat_cli_with_mcp_config():
    """--mcp-config flag appears in command when mcp_config_path is provided."""
    mcp_path = pathlib.Path("/tmp/test_mcp.json")
    with patch("subprocess.run", return_value=_make_completed_process("ok")) as mock_run:
        claude.chat(
            [{"role": "user", "content": "hi"}],
            system="sys",
            mcp_config_path=mcp_path,
        )
    cmd = mock_run.call_args[0][0]
    assert "--mcp-config" in cmd
    idx = cmd.index("--mcp-config")
    assert cmd[idx + 1] == str(mcp_path)
