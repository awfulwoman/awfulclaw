from __future__ import annotations

from pathlib import Path

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
