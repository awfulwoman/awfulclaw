#!/usr/bin/env python3
"""One-off migration: consolidate Telegram history into the primary channel.

Run once from the project root:
    uv run python scripts/migrate_primary_channel.py

Safe to run multiple times — checks before updating.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import aiosqlite
import sqlite_vec  # type: ignore[import-untyped]

TELEGRAM_CHANNEL = "888261035"
DB_PATH = Path(os.environ.get("DB_PATH", "state/store.db"))


async def main() -> None:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    db = await aiosqlite.connect(DB_PATH)
    await db.enable_load_extension(True)
    await db.load_extension(sqlite_vec.loadable_path())
    await db.enable_load_extension(False)

    # Add connector column if missing (same migration as Store.connect)
    cols_cursor = await db.execute("PRAGMA table_info(conversations)")
    cols = [row[1] for row in await cols_cursor.fetchall()]
    if "connector" not in cols:
        print("Adding connector column...")
        await db.execute(
            "ALTER TABLE conversations ADD COLUMN connector TEXT NOT NULL DEFAULT 'unknown'"
        )
        await db.commit()
        print("connector column added.")
    else:
        print("connector column already present.")

    # Count rows to migrate
    cursor = await db.execute(
        "SELECT COUNT(*) FROM conversations WHERE channel = ?",
        (TELEGRAM_CHANNEL,),
    )
    row = await cursor.fetchone()
    pending = row[0] if row else 0

    if pending == 0:
        cursor2 = await db.execute(
            "SELECT COUNT(*) FROM conversations WHERE channel = 'primary' AND connector = 'telegram'"
        )
        row2 = await cursor2.fetchone()
        already_migrated = row2[0] if row2 else 0
        if already_migrated > 0:
            print(f"Already migrated ({already_migrated} rows). Nothing to do.")
        else:
            print(f"No rows found for channel={TELEGRAM_CHANNEL!r}. Nothing to migrate.")
        await db.close()
        return

    print(f"Migrating {pending} rows from channel={TELEGRAM_CHANNEL!r} to 'primary'...")
    await db.execute(
        "UPDATE conversations SET connector = 'telegram' WHERE channel = ?",
        (TELEGRAM_CHANNEL,),
    )
    await db.execute(
        "UPDATE conversations SET channel = 'primary' WHERE channel = ?",
        (TELEGRAM_CHANNEL,),
    )
    await db.commit()
    print(f"Done. {pending} rows migrated.")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
