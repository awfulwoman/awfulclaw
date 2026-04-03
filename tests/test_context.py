"""Tests for ContextAssembler."""
from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agent.config import Settings
from agent.context import ContextAssembler
from agent.store import Schedule, Store


def _fake_embed(text: str) -> bytes:
    return struct.pack(f"{384}f", *([1.0] + [0.0] * 383))


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s
    await s.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    cfg = tmp_path / "agent_config"
    cfg.mkdir()
    (cfg / "PERSONALITY.md").write_text("You are Ralph.")
    (cfg / "PROTOCOLS.md").write_text("Always be helpful.")
    (cfg / "USER.md").write_text("Charlie is the owner.")
    return Settings(  # type: ignore[call-arg]
        agent_config_path=cfg,
        telegram={"bot_token": "x", "allowed_chat_ids": [1]},
    )


@pytest.mark.asyncio
async def test_build_includes_always_sections(store: Store, settings: Settings) -> None:
    assembler = ContextAssembler(store, settings)
    with patch("agent.store.embed", side_effect=_fake_embed):
        prompt = await assembler.build("hello", "charlie", "chan1")

    assert "Ralph" in prompt
    assert "Always be helpful" in prompt
    assert "Charlie is the owner" in prompt
    assert "Current Time" in prompt


@pytest.mark.asyncio
async def test_build_includes_facts(store: Store, settings: Settings) -> None:
    with patch("agent.store.embed", side_effect=_fake_embed):
        await store.set_fact("fav_color", "blue")
        assembler = ContextAssembler(store, settings)
        prompt = await assembler.build("what color?", None, "chan1")
    assert "fav_color" in prompt
    assert "blue" in prompt


@pytest.mark.asyncio
async def test_build_includes_people(store: Store, settings: Settings) -> None:
    with patch("agent.store.embed", side_effect=_fake_embed):
        await store.set_person("p1", "Alice", "a close friend")
        assembler = ContextAssembler(store, settings)
        prompt = await assembler.build("Alice mentioned something", None, "chan1")
    assert "Alice" in prompt


@pytest.mark.asyncio
async def test_build_includes_schedules(store: Store, settings: Settings) -> None:
    sched = Schedule(
        id="s1", name="morning", cron="0 8 * * *", fire_at=None,
        prompt="Say good morning", silent=False, tz="UTC",
        created_at="2026-01-01T00:00:00", last_run=None,
    )
    await store.upsert_schedule(sched)
    assembler = ContextAssembler(store, settings)
    with patch("agent.store.embed", side_effect=_fake_embed):
        prompt = await assembler.build("hi", None, "chan1")
    assert "morning" in prompt


@pytest.mark.asyncio
async def test_build_includes_personality_log(store: Store, settings: Settings) -> None:
    await store._db.execute(
        "INSERT INTO personality_log (entry, verdict, timestamp) VALUES (?, ?, ?)",
        ("Likes concise replies", "approved", "2026-01-01T00:00:00"),
    )
    await store._db.commit()
    assembler = ContextAssembler(store, settings)
    with patch("agent.store.embed", side_effect=_fake_embed):
        prompt = await assembler.build("hi", None, "chan1")
    assert "Likes concise replies" in prompt


@pytest.mark.asyncio
async def test_build_excludes_expired_personality_log(store: Store, settings: Settings) -> None:
    await store._db.execute(
        "INSERT INTO personality_log (entry, verdict, timestamp, expires_at) VALUES (?, ?, ?, ?)",
        ("Old note", "approved", "2025-01-01T00:00:00", "2025-06-01T00:00:00"),
    )
    await store._db.commit()
    assembler = ContextAssembler(store, settings)
    with patch("agent.store.embed", side_effect=_fake_embed):
        prompt = await assembler.build("hi", None, "chan1")
    assert "Old note" not in prompt


@pytest.mark.asyncio
async def test_build_excludes_rejected_personality_log(store: Store, settings: Settings) -> None:
    await store._db.execute(
        "INSERT INTO personality_log (entry, verdict, timestamp) VALUES (?, ?, ?)",
        ("Bad note", "rejected", "2026-01-01T00:00:00"),
    )
    await store._db.commit()
    assembler = ContextAssembler(store, settings)
    with patch("agent.store.embed", side_effect=_fake_embed):
        prompt = await assembler.build("hi", None, "chan1")
    assert "Bad note" not in prompt


@pytest.mark.asyncio
async def test_build_missing_config_files(store: Store, tmp_path: Path) -> None:
    """Missing agent_config files don't crash — just return empty sections."""
    empty_cfg = tmp_path / "empty_cfg"
    empty_cfg.mkdir()
    settings = Settings(  # type: ignore[call-arg]
        agent_config_path=empty_cfg,
        telegram={"bot_token": "x", "allowed_chat_ids": [1]},
    )
    assembler = ContextAssembler(store, settings)
    with patch("agent.store.embed", side_effect=_fake_embed):
        prompt = await assembler.build("hi", None, "chan1")
    assert "Current Time" in prompt


@pytest.mark.asyncio
async def test_build_includes_skill_names(store: Store, settings: Settings, tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "daily-briefing.md").write_text("# Daily briefing")
    (skills_dir / "email-triage.md").write_text("# Email triage")

    with patch("agent.context._list_skills", new=AsyncMock(return_value=["daily-briefing", "email-triage"])):
        assembler = ContextAssembler(store, settings)
        with patch("agent.store.embed", side_effect=_fake_embed):
            prompt = await assembler.build("hi", None, "chan1")
    assert "daily-briefing" in prompt
    assert "email-triage" in prompt
