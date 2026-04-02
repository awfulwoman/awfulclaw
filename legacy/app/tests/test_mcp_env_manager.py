"""Tests for MCP env_manager server."""

from __future__ import annotations

from pathlib import Path

import pytest

from awfulclaw_mcp.env_manager import env_keys, env_set


@pytest.fixture(autouse=True)
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_env_set_writes_key(tmp_path: Path) -> None:
    result = env_set("API_KEY", "sk-abc123")
    assert "API_KEY" in result
    assert (tmp_path / ".env").read_text().strip() == "API_KEY=sk-abc123"


def test_env_set_rejects_invalid_key() -> None:
    result = env_set("bad-key", "value")
    assert "Error" in result


def test_env_set_does_not_expose_value(tmp_path: Path) -> None:
    result = env_set("SECRET", "topsecret")
    assert "topsecret" not in result


def test_env_keys_returns_names(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FOO=bar\nBAZ=qux\n")
    result = env_keys()
    assert "FOO" in result
    assert "BAZ" in result
    assert "bar" not in result
    assert "qux" not in result


def test_env_keys_empty(tmp_path: Path) -> None:
    result = env_keys()
    assert "No keys" in result
