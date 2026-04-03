"""Tests for embedding generation and sqlite-vec search in Store."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest

from agent.store import Store, embed

_DIM = 384


def _vec(index: int) -> bytes:
    """Return a 384-dim unit vector with 1.0 at `index`, 0 elsewhere."""
    floats = [0.0] * _DIM
    floats[index] = 1.0
    return struct.pack(f"{_DIM}f", *floats)


def _mock_embed(mapping: dict[str, bytes]) -> Callable[[str], bytes]:
    """Return an embed mock that maps text prefixes to known vectors."""

    def _embed(text: str) -> bytes:
        for key, vec in mapping.items():
            if key in text:
                return vec
        return _vec(0)

    return _embed


@pytest.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


# --- embed() ---


def test_embed_returns_bytes() -> None:
    result = embed("hello world")
    assert isinstance(result, bytes)
    assert len(result) == _DIM * 4  # 384 float32 = 1536 bytes


def test_embed_different_texts_differ() -> None:
    a = embed("apple")
    b = embed("helicopter maintenance schedule")
    assert a != b


# --- search_facts ---


async def test_search_facts_ranks_by_similarity(store: Store) -> None:
    mapping = {
        "cats": _vec(0),   # similar to query
        "dogs": _vec(1),   # orthogonal to query
        "query": _vec(0),  # identical to cats
    }
    with patch("agent.store.embed", side_effect=_mock_embed(mapping)):
        await store.set_fact("cats", "Cats are independent pets")
        await store.set_fact("dogs", "Dogs are loyal companions")
        results = await store.search_facts("query about cats", limit=2)

    assert len(results) == 2
    assert results[0].key == "cats"
    assert results[1].key == "dogs"


async def test_search_facts_respects_limit(store: Store) -> None:
    with patch("agent.store.embed", return_value=_vec(0)):
        for i in range(5):
            await store.set_fact(f"fact_{i}", f"value {i}")
        results = await store.search_facts("anything", limit=3)

    assert len(results) == 3


async def test_search_facts_skips_null_embeddings(store: Store) -> None:
    # Directly insert a fact without an embedding
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await store._db.execute(
        "INSERT INTO facts (key, value, updated_at) VALUES (?, ?, ?)",
        ("no_emb", "no embedding here", now),
    )
    await store._db.commit()

    with patch("agent.store.embed", return_value=_vec(0)):
        results = await store.search_facts("anything")

    keys = {r.key for r in results}
    assert "no_emb" not in keys


# --- search_people ---


async def test_search_people_ranks_by_similarity(store: Store) -> None:
    mapping = {
        "Alice": _vec(0),   # similar to query
        "Bob": _vec(1),     # orthogonal to query
        "query": _vec(0),
    }
    with patch("agent.store.embed", side_effect=_mock_embed(mapping)):
        await store.set_person("alice", "Alice", "Alice loves hiking")
        await store.set_person("bob", "Bob", "Bob plays chess")
        results = await store.search_people("query about Alice", limit=2)

    assert len(results) == 2
    assert results[0].name == "Alice"
    assert results[1].name == "Bob"


async def test_search_people_respects_limit(store: Store) -> None:
    with patch("agent.store.embed", return_value=_vec(0)):
        for i in range(5):
            await store.set_person(f"p_{i}", f"Person {i}", f"content {i}")
        results = await store.search_people("anything", limit=2)

    assert len(results) == 2


# --- set_fact / set_person store embeddings ---


async def test_set_fact_stores_embedding(store: Store) -> None:
    with patch("agent.store.embed", return_value=_vec(0)):
        await store.set_fact("climate", "Earth is warming")

    cursor = await store._db.execute("SELECT embedding FROM facts WHERE key = 'climate'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == _vec(0)


async def test_set_person_stores_embedding(store: Store) -> None:
    with patch("agent.store.embed", return_value=_vec(1)):
        await store.set_person("eve", "Eve", "Eve is a developer")

    cursor = await store._db.execute("SELECT embedding FROM people WHERE id = 'eve'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == _vec(1)


async def test_set_fact_upsert_updates_embedding(store: Store) -> None:
    with patch("agent.store.embed", return_value=_vec(0)):
        await store.set_fact("key", "first value")
    with patch("agent.store.embed", return_value=_vec(2)):
        await store.set_fact("key", "updated value")

    cursor = await store._db.execute("SELECT embedding FROM facts WHERE key = 'key'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == _vec(2)
