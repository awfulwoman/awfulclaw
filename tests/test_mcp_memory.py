"""Unit tests for agent/mcp/memory.py"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import aiosqlite
import sqlite_vec  # type: ignore[import-untyped]
import pytest

import agent.mcp.memory as mem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    embedding BLOB,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    content TEXT NOT NULL,
    embedding BLOB,
    updated_at TEXT NOT NULL
);
"""

# 4-dim float32 bytes — small enough for tests, same size used as query embedding
_FAKE_EMB = struct.pack("4f", 0.1, 0.2, 0.3, 0.4)


async def _async_return(value: Any) -> Any:
    return value


async def _make_db(path: Path) -> None:
    """Create schema with sqlite_vec loaded so vec_distance_cosine works in tests."""
    async with aiosqlite.connect(path) as db:
        await db.enable_load_extension(True)
        await db.load_extension(sqlite_vec.loadable_path())
        await db.enable_load_extension(False)
        await db.executescript(_SCHEMA)
        await db.commit()


async def _read_fact(db_path: Path, key: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT key, value, updated_at FROM facts WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
    return {"key": row[0], "value": row[1], "updated_at": row[2]} if row else None


async def _read_person(db_path: Path, id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, name, content, updated_at FROM people WHERE id = ?", (id,)
        ) as cur:
            row = await cur.fetchone()
    return (
        {"id": row[0], "name": row[1], "content": row[2], "updated_at": row[3]}
        if row
        else None
    )


async def _insert_fact(db_path: Path, key: str, value: str, emb: bytes = _FAKE_EMB) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO facts (key, value, embedding, updated_at) VALUES (?, ?, ?, ?)",
            (key, value, emb, now),
        )
        await db.commit()


async def _insert_person(
    db_path: Path, id: str, name: str, content: str, emb: bytes = _FAKE_EMB
) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO people (id, name, content, embedding, updated_at) VALUES (?, ?, ?, ?, ?)",
            (id, name, content, emb, now),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# memory_write — facts
# ---------------------------------------------------------------------------


async def test_memory_write_fact_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_check_governance", lambda t, v: _async_return("approved"))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    result = await mem.memory_write(type="fact", key="favorite_color", value="blue")

    assert "fact" in result.lower()
    assert "favorite_color" in result
    row = await _read_fact(db_path, "favorite_color")
    assert row is not None
    assert row["value"] == "blue"


async def test_memory_write_fact_upserts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_check_governance", lambda t, v: _async_return("approved"))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    await mem.memory_write(type="fact", key="city", value="London")
    await mem.memory_write(type="fact", key="city", value="Paris")

    row = await _read_fact(db_path, "city")
    assert row is not None
    assert row["value"] == "Paris"


# ---------------------------------------------------------------------------
# memory_write — people
# ---------------------------------------------------------------------------


async def test_memory_write_person_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_check_governance", lambda t, v: _async_return("approved"))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    result = await mem.memory_write(
        type="person", key="alice-123", value="Alice Smith\nFriend from uni, likes hiking"
    )

    assert "person" in result.lower()
    row = await _read_person(db_path, "alice-123")
    assert row is not None
    assert row["name"] == "Alice Smith"
    assert row["content"] == "Friend from uni, likes hiking"


# ---------------------------------------------------------------------------
# memory_write — governance
# ---------------------------------------------------------------------------


async def test_memory_write_governance_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_check_governance", lambda t, v: _async_return("rejected"))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    result = await mem.memory_write(type="fact", key="bad", value="evil content")

    assert "governance rejected" in result.lower()
    row = await _read_fact(db_path, "bad")
    assert row is None


async def test_memory_write_invalid_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = await mem.memory_write(type="unknown", key="x", value="y")

    assert "Error" in result
    assert "fact" in result or "person" in result


# ---------------------------------------------------------------------------
# memory_search
# ---------------------------------------------------------------------------


async def test_memory_search_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    await _insert_fact(db_path, "color", "blue")
    await _insert_fact(db_path, "city", "Paris")

    results = await mem.memory_search(query="color preferences", type="fact")

    assert len(results) == 2
    assert all(r["type"] == "fact" for r in results)
    keys = {r["key"] for r in results}
    assert keys == {"color", "city"}


async def test_memory_search_people(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    await _insert_person(db_path, "alice-1", "Alice", "Friend from uni")

    results = await mem.memory_search(query="friend", type="person")

    assert len(results) == 1
    assert results[0]["type"] == "person"
    assert results[0]["name"] == "Alice"


async def test_memory_search_both_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    await _insert_fact(db_path, "weather", "sunny")
    await _insert_person(db_path, "bob-1", "Bob", "Colleague at work")

    results = await mem.memory_search(query="something")

    types = {r["type"] for r in results}
    assert "fact" in types
    assert "person" in types


async def test_memory_search_invalid_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agent.db"
    await _make_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(mem, "_embed", lambda text: _FAKE_EMB)

    results = await mem.memory_search(query="x", type="unknown")

    assert len(results) == 1
    assert "error" in results[0]
