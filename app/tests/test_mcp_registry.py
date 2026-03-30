"""Tests for MCP registry and config generation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from awfulclaw_mcp import generate_mcp_config
from awfulclaw_mcp.registry import MCPRegistry


def test_generate_mcp_config_schema():
    servers = {
        "web": {
            "command": "python",
            "args": ["-m", "awfulclaw_mcp.web"],
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
        "web": {"command": "python", "args": ["-m", "awfulclaw_mcp.web"], "env": {}},
        "search": {
            "command": "python",
            "args": ["-m", "awfulclaw_mcp.search"],
            "env": {"KEY": "val"},
        },
    }
    path = generate_mcp_config(servers)
    data = json.loads(path.read_text())
    assert set(data["mcpServers"].keys()) == {"web", "search"}


def test_registry_register_and_generate():
    reg = MCPRegistry()
    reg.register("web", "python", ["-m", "awfulclaw_mcp.web"])
    path = reg.generate_config()
    data = json.loads(path.read_text())
    assert "mcpServers" in data
    assert "web" in data["mcpServers"]
    entry = data["mcpServers"]["web"]
    assert entry["command"] == "python"
    assert entry["args"] == ["-m", "awfulclaw_mcp.web"]
    assert entry["env"] == {}


def test_registry_register_with_env():
    reg = MCPRegistry()
    reg.register(
        "imap", "python", ["-m", "awfulclaw_mcp.imap"], env={"IMAP_HOST": "imap.example.com"}
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


def test_load_from_config_basic(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "memory_write",
                        "command": "uv",
                        "args": ["run", "python", "-m", "awfulclaw_mcp.memory_write"],
                    }
                ]
            }
        )
    )
    reg = MCPRegistry()
    reg.load_from_config(cfg)
    assert not reg.is_empty()
    data = json.loads(reg.generate_config().read_text())
    assert "memory_write" in data["mcpServers"]


def test_load_from_config_env_required_skips_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "imap",
                        "command": "uv",
                        "args": ["run", "python", "-m", "awfulclaw_mcp.imap"],
                        "env_required": ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"],
                    }
                ]
            }
        )
    )
    reg = MCPRegistry()
    reg.load_from_config(cfg)
    assert reg.is_empty()


def test_load_from_config_env_required_registers_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.delenv("IMAP_PORT", raising=False)
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "imap",
                        "command": "uv",
                        "args": ["run", "python", "-m", "awfulclaw_mcp.imap"],
                        "env": {
                            "IMAP_HOST": "${IMAP_HOST}",
                            "IMAP_PORT": "${IMAP_PORT}",
                            "IMAP_USER": "${IMAP_USER}",
                            "IMAP_PASSWORD": "${IMAP_PASSWORD}",
                        },
                        "env_required": ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"],
                    }
                ]
            }
        )
    )
    reg = MCPRegistry()
    reg.load_from_config(cfg)
    assert not reg.is_empty()
    data = json.loads(reg.generate_config().read_text())
    env = data["mcpServers"]["imap"]["env"]
    assert env["IMAP_HOST"] == "imap.example.com"
    assert env["IMAP_USER"] == "user@example.com"
    assert env["IMAP_PORT"] == ""  # not set in env → empty string


def test_reload_if_changed(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps({"servers": [{"name": "s1", "command": "uv", "args": []}]}))
    reg = MCPRegistry()
    reg.load_from_config(cfg)
    assert not reg.reload_if_changed(cfg)  # mtime unchanged

    # Overwrite with new content and force a new mtime
    import time

    time.sleep(0.01)
    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {"name": "s1", "command": "uv", "args": []},
                    {"name": "s2", "command": "uv", "args": []},
                ]
            }
        )
    )
    # Manually bump mtime to ensure it differs
    new_mtime = cfg.stat().st_mtime + 1
    os.utime(cfg, (new_mtime, new_mtime))

    assert reg.reload_if_changed(cfg)
    data = json.loads(reg.generate_config().read_text())
    assert "s2" in data["mcpServers"]
