from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from agent.store import Schedule, Store


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


@pytest.mark.asyncio
async def test_add_and_retrieve_turns(store: Store) -> None:
    await store.add_turn("telegram:123", "user", "hello")
    await store.add_turn("telegram:123", "assistant", "hi")
    turns = await store.recent_turns("telegram:123", 10)
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].content == "hello"
    assert turns[1].role == "assistant"


@pytest.mark.asyncio
async def test_recent_turns_ordering(store: Store) -> None:
    for i in range(5):
        await store.add_turn("ch", "user", f"msg{i}")
    turns = await store.recent_turns("ch", 3)
    assert len(turns) == 3
    # most recent 3, returned oldest-first
    assert turns[0].content == "msg2"
    assert turns[1].content == "msg3"
    assert turns[2].content == "msg4"


@pytest.mark.asyncio
async def test_turns_channel_isolation(store: Store) -> None:
    await store.add_turn("ch1", "user", "a")
    await store.add_turn("ch2", "user", "b")
    assert len(await store.recent_turns("ch1", 10)) == 1
    assert len(await store.recent_turns("ch2", 10)) == 1


@pytest.mark.asyncio
async def test_schedule_upsert_and_list(store: Store) -> None:
    s = Schedule(id="s1", name="daily", cron="0 9 * * *", fire_at=None,
                 prompt="remind me", silent=False, tz="UTC", created_at="2026-01-01T00:00:00+00:00", last_run=None)
    await store.upsert_schedule(s)
    schedules = await store.list_schedules()
    assert len(schedules) == 1
    assert schedules[0].name == "daily"
    assert schedules[0].silent is False

    # update
    s2 = Schedule(id="s1", name="daily", cron="0 10 * * *", fire_at=None,
                  prompt="remind me updated", silent=True, tz="UTC", created_at="2026-01-01T00:00:00+00:00", last_run=None)
    await store.upsert_schedule(s2)
    schedules = await store.list_schedules()
    assert len(schedules) == 1
    assert schedules[0].cron == "0 10 * * *"
    assert schedules[0].silent is True


@pytest.mark.asyncio
async def test_schedule_delete(store: Store) -> None:
    s = Schedule(id="s1", name="once", cron=None, fire_at="2026-01-01T09:00:00+00:00",
                 prompt="do thing", silent=False, tz="UTC", created_at="2026-01-01T00:00:00+00:00", last_run=None)
    await store.upsert_schedule(s)
    await store.delete_schedule("s1")
    assert await store.list_schedules() == []


@pytest.mark.asyncio
async def test_add_turn_with_connector(store: Store) -> None:
    turn = await store.add_turn("primary", "user", "hello", connector="telegram")
    assert turn.connector == "telegram"
    turns = await store.recent_turns("primary", 10)
    assert turns[0].connector == "telegram"


@pytest.mark.asyncio
async def test_add_turn_default_connector_is_unknown(store: Store) -> None:
    turn = await store.add_turn("primary", "user", "hello")
    assert turn.connector == "unknown"


@pytest.mark.asyncio
async def test_store_connect_is_idempotent_with_connector_column(tmp_path: Path) -> None:
    """Connecting twice to the same DB must not fail even if connector column already exists."""
    s1 = await Store.connect(tmp_path / "test.db")
    await s1.add_turn("primary", "user", "hi", connector="telegram")
    await s1.close()
    s2 = await Store.connect(tmp_path / "test.db")
    turns = await s2.recent_turns("primary", 10)
    assert turns[0].connector == "telegram"
    await s2.close()
