"""Tests for MCP registry and config generation."""

from __future__ import annotations

import json

from awfulclaw.mcp import generate_mcp_config
from awfulclaw.mcp.registry import MCPRegistry


def test_generate_mcp_config_schema():
    servers = {
        "web": {
            "command": "python",
            "args": ["-m", "awfulclaw.mcp.web"],
            "env": {},
        }
    }
    path = generate_mcp_config(servers)
    assert path.exists()
    data = json.loads(path.read_text())
    assert "mcpServers" in data
    assert data["mcpServers"] == servers


def test_generate_mcp_config_multiple_servers():
    servers = {
        "web": {"command": "python", "args": ["-m", "awfulclaw.mcp.web"], "env": {}},
        "search": {
            "command": "python",
            "args": ["-m", "awfulclaw.mcp.search"],
            "env": {"KEY": "val"},
        },
    }
    path = generate_mcp_config(servers)
    data = json.loads(path.read_text())
    assert set(data["mcpServers"].keys()) == {"web", "search"}


def test_registry_register_and_generate():
    reg = MCPRegistry()
    reg.register("web", "python", ["-m", "awfulclaw.mcp.web"])
    path = reg.generate_config()
    data = json.loads(path.read_text())
    assert "mcpServers" in data
    assert "web" in data["mcpServers"]
    entry = data["mcpServers"]["web"]
    assert entry["command"] == "python"
    assert entry["args"] == ["-m", "awfulclaw.mcp.web"]
    assert entry["env"] == {}


def test_registry_register_with_env():
    reg = MCPRegistry()
    reg.register(
        "imap", "python", ["-m", "awfulclaw.mcp.imap"], env={"IMAP_HOST": "imap.example.com"}
    )
    path = reg.generate_config()
    data = json.loads(path.read_text())
    assert data["mcpServers"]["imap"]["env"] == {"IMAP_HOST": "imap.example.com"}


def test_registry_is_empty():
    reg = MCPRegistry()
    assert reg.is_empty()
    reg.register("x", "python", [])
    assert not reg.is_empty()


def test_generate_mcp_config_empty():
    path = generate_mcp_config({})
    data = json.loads(path.read_text())
    assert data == {"mcpServers": {}}
