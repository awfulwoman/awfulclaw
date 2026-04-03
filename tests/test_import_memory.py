"""Tests for scripts/import_memory.py."""
from __future__ import annotations

import sqlite3
import struct
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import import_memory  # noqa: E402

_DIM = 384


def _vec() -> bytes:
    return struct.pack(f"{_DIM}f", *([0.0] * (_DIM - 1) + [1.0]))


def _make_legacy_db(path: Path, facts: list[tuple[str, str]], people: list[tuple[str, str]]) -> Path:
    """Create a legacy SQLite DB with facts and people tables."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE facts (key TEXT PRIMARY KEY, content TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE people (name TEXT PRIMARY KEY, content TEXT, updated_at TEXT)"
    )
    for key, content in facts:
        conn.execute(
            "INSERT INTO facts (key, content, updated_at) VALUES (?, ?, ?)",
            (key, content, "2024-01-01T00:00:00+00:00"),
        )
    for name, content in people:
        conn.execute(
            "INSERT INTO people (name, content, updated_at) VALUES (?, ?, ?)",
            (name, content, "2024-01-01T00:00:00+00:00"),
        )
    conn.commit()
    conn.close()
    return path


@pytest.mark.asyncio
async def test_import_facts(tmp_path: Path) -> None:
    """Imports facts from legacy DB into new schema."""
    legacy = _make_legacy_db(
        tmp_path / "legacy.db",
        facts=[("color", "blue"), ("city", "Berlin")],
        people=[],
    )

    with patch("agent.store.embed", return_value=_vec()):
        fi, fs, pi, ps = await import_memory.run(legacy, db_path=tmp_path / "agent.db")

    assert fi == 2
    assert fs == 0
    assert pi == 0
    assert ps == 0

    from agent.store import Store

    store = await Store.connect(tmp_path / "agent.db")
    try:
        color = await store.get_fact("color")
        assert color is not None
        assert color.value == "blue"
        city = await store.get_fact("city")
        assert city is not None
        assert city.value == "Berlin"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_import_people(tmp_path: Path) -> None:
    """Imports people from legacy DB into new schema."""
    legacy = _make_legacy_db(
        tmp_path / "legacy.db",
        facts=[],
        people=[("Alice", "Alice is a friend."), ("Bob", "Bob is a colleague.")],
    )

    with patch("agent.store.embed", return_value=_vec()):
        fi, fs, pi, ps = await import_memory.run(legacy, db_path=tmp_path / "agent.db")

    assert fi == 0
    assert pi == 2

    from agent.store import Store

    store = await Store.connect(tmp_path / "agent.db")
    try:
        alice = await store.get_person("Alice")
        assert alice is not None
        assert alice.name == "Alice"
        assert alice.content == "Alice is a friend."
        assert alice.phone is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_embeddings_generated(tmp_path: Path) -> None:
    """Embeddings are generated for every imported row."""
    legacy = _make_legacy_db(
        tmp_path / "legacy.db",
        facts=[("weather", "sunny")],
        people=[("Carol", "Carol is my sister.")],
    )

    embed_calls: list[str] = []

    def _recording_embed(text: str) -> bytes:
        embed_calls.append(text)
        return _vec()

    with patch("agent.store.embed", side_effect=_recording_embed):
        await import_memory.run(legacy, db_path=tmp_path / "agent.db")

    # embed() called once for the fact and once for the person
    assert len(embed_calls) == 2


@pytest.mark.asyncio
async def test_skip_duplicate_facts(tmp_path: Path) -> None:
    """Re-importing the same facts skips duplicates."""
    db = tmp_path / "agent.db"
    legacy = _make_legacy_db(
        tmp_path / "legacy.db",
        facts=[("x", "1"), ("y", "2")],
        people=[],
    )

    with patch("agent.store.embed", return_value=_vec()):
        fi1, fs1, _, _ = await import_memory.run(legacy, db_path=db)
        fi2, fs2, _, _ = await import_memory.run(legacy, db_path=db)

    assert fi1 == 2 and fs1 == 0
    assert fi2 == 0 and fs2 == 2


@pytest.mark.asyncio
async def test_skip_duplicate_people(tmp_path: Path) -> None:
    """Re-importing the same people skips duplicates."""
    db = tmp_path / "agent.db"
    legacy = _make_legacy_db(
        tmp_path / "legacy.db",
        facts=[],
        people=[("Dan", "Dan is a neighbor.")],
    )

    with patch("agent.store.embed", return_value=_vec()):
        _, _, pi1, ps1 = await import_memory.run(legacy, db_path=db)
        _, _, pi2, ps2 = await import_memory.run(legacy, db_path=db)

    assert pi1 == 1 and ps1 == 0
    assert pi2 == 0 and ps2 == 1


@pytest.mark.asyncio
async def test_missing_tables_handled(tmp_path: Path) -> None:
    """Legacy DB with no facts/people tables doesn't crash."""
    legacy = tmp_path / "empty.db"
    conn = sqlite3.connect(legacy)
    conn.close()  # empty DB — no tables

    with patch("agent.store.embed", return_value=_vec()):
        fi, fs, pi, ps = await import_memory.run(legacy, db_path=tmp_path / "agent.db")

    assert fi == 0 and fs == 0 and pi == 0 and ps == 0


def test_read_legacy(tmp_path: Path) -> None:
    """_read_legacy returns correct facts and people from legacy DB."""
    legacy = _make_legacy_db(
        tmp_path / "legacy.db",
        facts=[("a", "alpha")],
        people=[("Eve", "Eve is a developer.")],
    )

    facts, people = import_memory._read_legacy(legacy)

    assert len(facts) == 1
    assert facts[0][0] == "a" and facts[0][1] == "alpha"
    assert len(people) == 1
    assert people[0][0] == "Eve" and people[0][1] == "Eve is a developer."
