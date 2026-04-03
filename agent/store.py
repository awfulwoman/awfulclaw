from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import sqlite_vec  # type: ignore[import-untyped]

_embedding_model: Any = None


def embed(text: str) -> bytes:
    """Encode text as raw float32 bytes using all-MiniLM-L6-v2 (384 dims)."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    import numpy as np

    vec = _embedding_model.encode(text, convert_to_numpy=True)
    return vec.astype(np.float32).tobytes()


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

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    cron TEXT,
    fire_at TEXT,
    prompt TEXT NOT NULL,
    silent INTEGER NOT NULL DEFAULT 0,
    tz TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_run TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personality_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT NOT NULL,
    verdict TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    expires_at TEXT
);
"""

_EXPECTED_TABLES = {"facts", "people", "conversations", "schedules", "kv", "personality_log"}


@dataclass
class Turn:
    id: int
    channel: str
    role: str
    content: str
    timestamp: str


@dataclass
class Schedule:
    id: str
    name: str
    cron: Optional[str]
    fire_at: Optional[str]
    prompt: str
    silent: bool
    tz: str
    created_at: str
    last_run: Optional[str]


@dataclass
class Fact:
    key: str
    value: str
    updated_at: str


@dataclass
class Person:
    id: str
    name: str
    phone: Optional[str]
    content: str
    updated_at: str


class Store:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    @classmethod
    async def connect(cls, db_path: Path) -> "Store":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(db_path)
        await db.enable_load_extension(True)
        await db.load_extension(sqlite_vec.loadable_path())
        await db.enable_load_extension(False)
        await db.executescript(_SCHEMA)
        await db.commit()
        return cls(db)

    async def check_schema(self) -> None:
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        existing = {row[0] for row in rows}
        missing = _EXPECTED_TABLES - existing
        if missing:
            raise RuntimeError(f"Missing tables: {', '.join(sorted(missing))}")

    async def close(self) -> None:
        await self._db.close()

    # --- kv ---

    async def kv_get(self, key: str) -> Optional[str]:
        cursor = await self._db.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None

    async def kv_set(self, key: str, value: str) -> None:
        await self._db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._db.commit()

    # --- facts ---

    async def get_fact(self, key: str) -> Optional[Fact]:
        cursor = await self._db.execute(
            "SELECT key, value, updated_at FROM facts WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return Fact(key=row[0], value=row[1], updated_at=row[2]) if row else None

    async def set_fact(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        emb = embed(f"{key}: {value}")
        await self._db.execute(
            "INSERT INTO facts (key, value, embedding, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, embedding = excluded.embedding, updated_at = excluded.updated_at",
            (key, value, emb, now),
        )
        await self._db.commit()

    async def search_facts(self, query: str, limit: int = 10) -> list[Fact]:
        query_emb = embed(query)
        cursor = await self._db.execute(
            "SELECT key, value, updated_at FROM facts "
            "WHERE embedding IS NOT NULL "
            "ORDER BY vec_distance_cosine(embedding, ?) "
            "LIMIT ?",
            (query_emb, limit),
        )
        rows = await cursor.fetchall()
        return [Fact(key=r[0], value=r[1], updated_at=r[2]) for r in rows]

    async def list_facts(self) -> list[Fact]:
        cursor = await self._db.execute("SELECT key, value, updated_at FROM facts ORDER BY key")
        rows = await cursor.fetchall()
        return [Fact(key=r[0], value=r[1], updated_at=r[2]) for r in rows]

    # --- people ---

    async def get_person(self, id: str) -> Optional[Person]:
        cursor = await self._db.execute(
            "SELECT id, name, phone, content, updated_at FROM people WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return Person(id=row[0], name=row[1], phone=row[2], content=row[3], updated_at=row[4]) if row else None

    async def set_person(self, id: str, name: str, content: str, phone: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        emb = embed(f"{name}: {content}")
        await self._db.execute(
            "INSERT INTO people (id, name, phone, content, embedding, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, phone = excluded.phone, "
            "content = excluded.content, embedding = excluded.embedding, updated_at = excluded.updated_at",
            (id, name, phone, content, emb, now),
        )
        await self._db.commit()

    async def search_people(self, query: str, limit: int = 10) -> list[Person]:
        query_emb = embed(query)
        cursor = await self._db.execute(
            "SELECT id, name, phone, content, updated_at FROM people "
            "WHERE embedding IS NOT NULL "
            "ORDER BY vec_distance_cosine(embedding, ?) "
            "LIMIT ?",
            (query_emb, limit),
        )
        rows = await cursor.fetchall()
        return [Person(id=r[0], name=r[1], phone=r[2], content=r[3], updated_at=r[4]) for r in rows]

    async def list_people(self) -> list[Person]:
        cursor = await self._db.execute(
            "SELECT id, name, phone, content, updated_at FROM people ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [Person(id=r[0], name=r[1], phone=r[2], content=r[3], updated_at=r[4]) for r in rows]

    # --- conversations ---

    async def add_turn(self, channel: str, role: str, content: str) -> Turn:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO conversations (channel, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (channel, role, content, now),
        )
        await self._db.commit()
        assert cursor.lastrowid is not None
        return Turn(id=cursor.lastrowid, channel=channel, role=role, content=content, timestamp=now)

    async def recent_turns(self, channel: str, limit: int) -> list[Turn]:
        cursor = await self._db.execute(
            "SELECT id, channel, role, content, timestamp FROM conversations "
            "WHERE channel = ? ORDER BY timestamp DESC LIMIT ?",
            (channel, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed([Turn(id=r[0], channel=r[1], role=r[2], content=r[3], timestamp=r[4]) for r in rows]))

    # --- schedules ---

    async def list_schedules(self) -> list[Schedule]:
        cursor = await self._db.execute(
            "SELECT id, name, cron, fire_at, prompt, silent, tz, created_at, last_run FROM schedules ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [
            Schedule(id=r[0], name=r[1], cron=r[2], fire_at=r[3], prompt=r[4], silent=bool(r[5]), tz=r[6], created_at=r[7], last_run=r[8])
            for r in rows
        ]

    async def upsert_schedule(self, schedule: Schedule) -> None:
        await self._db.execute(
            "INSERT INTO schedules (id, name, cron, fire_at, prompt, silent, tz, created_at, last_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, cron = excluded.cron, "
            "fire_at = excluded.fire_at, prompt = excluded.prompt, silent = excluded.silent, "
            "tz = excluded.tz, last_run = excluded.last_run",
            (schedule.id, schedule.name, schedule.cron, schedule.fire_at, schedule.prompt,
             int(schedule.silent), schedule.tz, schedule.created_at, schedule.last_run),
        )
        await self._db.commit()

    async def delete_schedule(self, id: str) -> None:
        await self._db.execute("DELETE FROM schedules WHERE id = ?", (id,))
        await self._db.commit()
