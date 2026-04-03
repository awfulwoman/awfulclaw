import pytest
from pathlib import Path

from agent.store import Store


@pytest.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


async def test_tables_created_on_fresh_db(tmp_path: Path) -> None:
    s = await Store.connect(tmp_path / "fresh.db")
    try:
        cursor = await s._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}
        assert {"facts", "people", "conversations", "schedules", "kv", "personality_log"}.issubset(
            table_names
        )
    finally:
        await s.close()


async def test_check_schema_passes_after_creation(store: Store) -> None:
    await store.check_schema()  # should not raise


async def test_check_schema_raises_on_missing_table(tmp_path: Path) -> None:
    import aiosqlite

    db = await aiosqlite.connect(tmp_path / "partial.db")
    await db.execute("CREATE TABLE facts (key TEXT PRIMARY KEY, value TEXT NOT NULL, embedding BLOB, updated_at TEXT NOT NULL)")
    await db.commit()
    s = Store(db)
    try:
        with pytest.raises(RuntimeError, match="Missing tables"):
            await s.check_schema()
    finally:
        await s.close()
