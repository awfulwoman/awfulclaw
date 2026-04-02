"""Tests for MCP mcp_manager server tools."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from awfulclaw_mcp.mcp_manager import (
    _check_server_status,
    mcp_server_diagnose,
    mcp_server_restart,
    mcp_server_status,
)


def _make_config(servers: list[dict[str, Any]], tmp_path: Path) -> Path:
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps({"servers": servers}))
    return cfg


@pytest.fixture()
def simple_config(tmp_path: Path) -> Path:
    return _make_config(
        [
            {"name": "memory_write", "command": "uv", "args": ["run", "python", "-m", "awfulclaw_mcp.memory_write"]},
            {
                "name": "imap",
                "command": "uv",
                "args": ["run", "python", "-m", "awfulclaw_mcp.imap"],
                "env_required": ["IMAP_HOST", "IMAP_USER"],
            },
        ],
        tmp_path,
    )


# --- _check_server_status ---

def test_check_status_loaded_when_no_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _check_server_status({"name": "foo", "command": "x", "args": []}) == "loaded"


def test_check_status_loaded_when_vars_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "val")
    entry = {"name": "foo", "command": "x", "args": [], "env_required": ["MY_KEY"]}
    assert _check_server_status(entry) == "loaded"


def test_check_status_skipped_when_var_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_VAR", raising=False)
    entry = {"name": "foo", "command": "x", "args": [], "env_required": ["MISSING_VAR"]}
    result = _check_server_status(entry)
    assert "skipped" in result
    assert "MISSING_VAR" in result


# --- mcp_server_status ---

def test_status_shows_loaded_and_skipped(
    simple_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.delenv("IMAP_USER", raising=False)
    with patch("awfulclaw_mcp.mcp_manager._config_path", return_value=simple_config):
        result = mcp_server_status()
    assert "memory_write" in result
    assert "loaded" in result
    assert "imap" in result
    assert "skipped" in result
    assert "IMAP_HOST" in result


def test_status_empty_config(tmp_path: Path) -> None:
    cfg = _make_config([], tmp_path)
    with patch("awfulclaw_mcp.mcp_manager._config_path", return_value=cfg):
        result = mcp_server_status()
    assert "No MCP servers" in result


# --- mcp_server_diagnose ---

def test_diagnose_unknown_server(simple_config: Path) -> None:
    with patch("awfulclaw_mcp.mcp_manager._config_path", return_value=simple_config):
        result = mcp_server_diagnose("nonexistent")
    assert "not found" in result


def test_diagnose_skipped_server(
    simple_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.delenv("IMAP_USER", raising=False)
    with patch("awfulclaw_mcp.mcp_manager._config_path", return_value=simple_config):
        result = mcp_server_diagnose("imap")
    assert "cannot be started" in result
    assert "skipped" in result


def test_diagnose_healthy_server(simple_config: Path) -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = None  # still running after 3s
    with (
        patch("awfulclaw_mcp.mcp_manager._config_path", return_value=simple_config),
        patch("awfulclaw_mcp.mcp_manager.subprocess.Popen", return_value=mock_proc),
        patch("time.sleep"),
    ):
        result = mcp_server_diagnose("memory_write")
    assert "healthy" in result
    mock_proc.terminate.assert_called_once()


def test_diagnose_crashing_server(simple_config: Path) -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = ("", "ImportError: No module named foo")
    with (
        patch("awfulclaw_mcp.mcp_manager._config_path", return_value=simple_config),
        patch("awfulclaw_mcp.mcp_manager.subprocess.Popen", return_value=mock_proc),
        patch("time.sleep"),
    ):
        result = mcp_server_diagnose("memory_write")
    assert "exited with code 1" in result
    assert "ImportError" in result


def test_diagnose_popen_exception(simple_config: Path) -> None:
    with (
        patch("awfulclaw_mcp.mcp_manager._config_path", return_value=simple_config),
        patch(
            "awfulclaw_mcp.mcp_manager.subprocess.Popen",
            side_effect=FileNotFoundError("command not found"),
        ),
    ):
        result = mcp_server_diagnose("memory_write")
    assert "Failed to start" in result


# --- mcp_server_restart ---

def test_restart_writes_flag_and_calls_script(tmp_path: Path) -> None:
    flag = tmp_path / "memory" / ".restart_requested"
    flag.parent.mkdir(parents=True)
    mock_popen = MagicMock()
    with (
        patch("awfulclaw_mcp.mcp_manager._project_root", return_value=tmp_path),
        patch("awfulclaw_mcp.mcp_manager.subprocess.Popen", return_value=mock_popen),
    ):
        result = mcp_server_restart()
    assert flag.exists()
    assert "Restarting" in result
    mock_popen  # Popen was called
