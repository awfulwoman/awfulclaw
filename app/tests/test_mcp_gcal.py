"""Tests for MCP gcal server."""

from __future__ import annotations


def test_token_path_is_outside_memory() -> None:
    from awfulclaw_mcp.gcal import _token_path

    path = _token_path()
    assert path.name == "gcal_token.json"
    assert ".config" in str(path)
    assert "awfulclaw" in str(path)
    assert "memory" not in str(path)
