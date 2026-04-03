"""Tests for agent/handlers/knowledge_flush.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.bus import ScheduleEvent
from agent.handlers.knowledge_flush import DAILY_FLUSH_SCHEDULE_NAME, KnowledgeFlushHandler
from agent.store import Fact, Person, Schedule


def _make_schedule(name: str = DAILY_FLUSH_SCHEDULE_NAME) -> Schedule:
    return Schedule(
        id="s1",
        name=name,
        cron="0 2 * * *",
        fire_at=None,
        prompt="daily knowledge flush",
        silent=True,
        tz="",
        created_at="2026-01-01T00:00:00+00:00",
        last_run=None,
    )


def _make_store(
    facts: list[Fact] | None = None,
    people: list[Person] | None = None,
    schedules: list[Schedule] | None = None,
) -> MagicMock:
    store = MagicMock()
    store.list_facts = AsyncMock(return_value=facts or [])
    store.list_people = AsyncMock(return_value=people or [])
    store.list_schedules = AsyncMock(return_value=schedules or [])
    store.upsert_schedule = AsyncMock()
    return store


# --- flush: content matches DB state ---


@pytest.mark.asyncio
async def test_flush_writes_facts(tmp_path: Path) -> None:
    facts = [
        Fact(key="color", value="blue", updated_at="2026-01-01T00:00:00+00:00"),
        Fact(key="city", value="Berlin", updated_at="2026-01-02T00:00:00+00:00"),
    ]
    store = _make_store(facts=facts)
    handler = KnowledgeFlushHandler(store, tmp_path / "vault")
    await handler.flush()

    content = (tmp_path / "vault" / "facts.md").read_text()
    assert "## color" in content
    assert "blue" in content
    assert "## city" in content
    assert "Berlin" in content


@pytest.mark.asyncio
async def test_flush_writes_people(tmp_path: Path) -> None:
    people = [
        Person(id="p1", name="Alice", phone="+49123", content="friend", updated_at="2026-01-01T00:00:00+00:00"),
        Person(id="p2", name="Bob", phone=None, content="colleague", updated_at="2026-01-02T00:00:00+00:00"),
    ]
    store = _make_store(people=people)
    handler = KnowledgeFlushHandler(store, tmp_path / "vault")
    await handler.flush()

    content = (tmp_path / "vault" / "people.md").read_text()
    assert "## Alice" in content
    assert "+49123" in content
    assert "## Bob" in content
    assert "colleague" in content
    # Bob has no phone — phone line should not appear for him
    assert content.count("**Phone:**") == 1


@pytest.mark.asyncio
async def test_flush_empty_store(tmp_path: Path) -> None:
    store = _make_store()
    handler = KnowledgeFlushHandler(store, tmp_path / "vault")
    await handler.flush()

    assert (tmp_path / "vault" / "facts.md").exists()
    assert (tmp_path / "vault" / "people.md").exists()


# --- atomic writes ---


@pytest.mark.asyncio
async def test_atomic_write_uses_rename(tmp_path: Path) -> None:
    """Verify that flush uses os.rename (atomic) not direct write."""
    store = _make_store()
    vault = tmp_path / "vault"
    vault.mkdir()
    handler = KnowledgeFlushHandler(store, vault)

    rename_calls: list[tuple[object, object]] = []
    original_rename = __import__("os").rename

    def recording_rename(src: object, dst: object) -> None:
        rename_calls.append((src, dst))
        original_rename(src, dst)

    with patch("agent.handlers.knowledge_flush.os.rename", side_effect=recording_rename):
        await handler.flush()

    # Should have called rename for both facts.md and people.md
    assert len(rename_calls) == 2
    renamed_dsts = [Path(str(dst)).name for _, dst in rename_calls]
    assert "facts.md" in renamed_dsts
    assert "people.md" in renamed_dsts


@pytest.mark.asyncio
async def test_atomic_write_no_tmp_left_on_success(tmp_path: Path) -> None:
    store = _make_store()
    vault = tmp_path / "vault"
    handler = KnowledgeFlushHandler(store, vault)
    await handler.flush()

    remaining = list(vault.iterdir())
    names = [f.name for f in remaining]
    assert "facts.md.tmp" not in names
    assert "people.md.tmp" not in names


# --- handle: only flushes for daily-flush schedule ---


@pytest.mark.asyncio
async def test_handle_flushes_for_daily_flush(tmp_path: Path) -> None:
    store = _make_store()
    handler = KnowledgeFlushHandler(store, tmp_path / "vault")
    await handler.handle(ScheduleEvent(schedule=_make_schedule(DAILY_FLUSH_SCHEDULE_NAME)))

    assert (tmp_path / "vault" / "facts.md").exists()


@pytest.mark.asyncio
async def test_handle_ignores_other_schedules(tmp_path: Path) -> None:
    store = _make_store()
    vault = tmp_path / "vault"
    handler = KnowledgeFlushHandler(store, vault)
    await handler.handle(ScheduleEvent(schedule=_make_schedule("other-schedule")))

    assert not vault.exists()


# --- ensure_default_schedule ---


@pytest.mark.asyncio
async def test_ensure_creates_schedule_when_missing(tmp_path: Path) -> None:
    store = _make_store(schedules=[])
    handler = KnowledgeFlushHandler(store, tmp_path / "vault")
    await handler.ensure_default_schedule()

    store.upsert_schedule.assert_called_once()
    created: Schedule = store.upsert_schedule.call_args[0][0]
    assert created.name == DAILY_FLUSH_SCHEDULE_NAME
    assert created.cron == "0 2 * * *"
    assert created.silent is True


@pytest.mark.asyncio
async def test_ensure_skips_when_schedule_exists(tmp_path: Path) -> None:
    existing = _make_schedule(DAILY_FLUSH_SCHEDULE_NAME)
    store = _make_store(schedules=[existing])
    handler = KnowledgeFlushHandler(store, tmp_path / "vault")
    await handler.ensure_default_schedule()

    store.upsert_schedule.assert_not_called()
