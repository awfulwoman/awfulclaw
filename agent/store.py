from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite


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
        await self._db.execute(
            "INSERT INTO facts (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )
        await self._db.commit()

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
        await self._db.execute(
            "INSERT INTO people (id, name, phone, content, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, phone = excluded.phone, "
            "content = excluded.content, updated_at = excluded.updated_at",
            (id, name, phone, content, now),
        )
        await self._db.commit()

    async def list_people(self) -> list[Person]:
        cursor = await self._db.execute(
            "SELECT id, name, phone, content, updated_at FROM people ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [Person(id=r[0], name=r[1], phone=r[2], content=r[3], updated_at=r[4]) for r in rows]
