"""Unit tests for agent/mcp/env_manager.py"""
from __future__ import annotations

import tempfile
from pathlib import Path

import aiosqlite
import pytest

import agent.mcp.env_manager as em


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_env(path: Path, content: str) -> None:
    path.write_text(content)


async def _make_db(path: Path) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        await db.commit()


async def _read_kv(db_path: Path, key: str) -> str | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT value FROM kv WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# env_keys tests
# ---------------------------------------------------------------------------


def test_env_keys_returns_key_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env_keys() returns only key names, not values."""
    env_file = tmp_path / ".env"
    _write_env(env_file, "FOO=secret1\nBAR=secret2\n")
    monkeypatch.setenv("ENV_PATH", str(env_file))

    keys = em.env_keys()
    assert keys == ["FOO", "BAR"]


def test_env_keys_skips_comments_and_blanks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env_keys() ignores comment lines and blank lines."""
    env_file = tmp_path / ".env"
    _write_env(env_file, "# comment\n\nFOO=val\n# another\nBAR=val2\n")
    monkeypatch.setenv("ENV_PATH", str(env_file))

    keys = em.env_keys()
    assert keys == ["FOO", "BAR"]


def test_env_keys_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env_keys() returns [] when .env doesn't exist."""
    monkeypatch.setenv("ENV_PATH", str(tmp_path / "nonexistent.env"))
    assert em.env_keys() == []


def test_env_keys_values_not_in_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm values never appear in env_keys() output."""
    env_file = tmp_path / ".env"
    _write_env(env_file, "SECRET_TOKEN=supersensitive\n")
    monkeypatch.setenv("ENV_PATH", str(env_file))

    result = em.env_keys()
    assert "supersensitive" not in str(result)
    assert result == ["SECRET_TOKEN"]


# ---------------------------------------------------------------------------
# env_set tests
# ---------------------------------------------------------------------------


async def test_env_set_registers_pending_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env_set(key) writes the pending marker to store.kv."""
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))

    result = await em.env_set("MY_API_KEY")
    assert "MY_API_KEY" in result

    stored = await _read_kv(db_path, em._PENDING_KEY)
    assert stored == "MY_API_KEY"


async def test_env_set_overwrites_existing_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env_set() replaces any previously pending key."""
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))

    await em.env_set("FIRST_KEY")
    await em.env_set("SECOND_KEY")

    stored = await _read_kv(db_path, em._PENDING_KEY)
    assert stored == "SECOND_KEY"


async def test_env_set_return_message_mentions_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env_set() return message includes the key name."""
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))

    result = await em.env_set("STRIPE_KEY")
    assert "STRIPE_KEY" in result


def test_no_env_get_tool() -> None:
    """Confirm env_get does not exist in this module (write-only design)."""
    assert not hasattr(em, "env_get")
