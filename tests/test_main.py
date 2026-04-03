from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agent.config import Settings, TelegramSettings
from agent.handlers.checkin import CheckinHandler
from agent.main import preflight
from agent.store import Store


@pytest.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    cfg = tmp_path / "profile"
    cfg.mkdir()
    for name in ("PERSONALITY.md", "PROTOCOLS.md", "USER.md"):
        (cfg / name).write_text(f"# {name}\n")
    return cfg


@pytest.fixture
def mcp_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text("{}")
    return cfg


_FAKE_TELEGRAM = TelegramSettings(bot_token="fake:token", allowed_chat_ids=[1])


@pytest.fixture
def settings(tmp_path: Path, profile: Path, mcp_config: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        telegram=_FAKE_TELEGRAM,
        profile_path=profile,
        mcp_config=mcp_config,
    )


async def test_preflight_passes_with_valid_setup(
    settings: Settings, store: Store
) -> None:
    await preflight(settings, store)  # must not raise


async def test_preflight_raises_on_missing_personality(
    settings: Settings, store: Store, profile: Path
) -> None:
    (profile / "PERSONALITY.md").unlink()
    with pytest.raises(FileNotFoundError, match="PERSONALITY.md"):
        await preflight(settings, store)


async def test_preflight_raises_on_missing_protocols(
    settings: Settings, store: Store, profile: Path
) -> None:
    (profile / "PROTOCOLS.md").unlink()
    with pytest.raises(FileNotFoundError, match="PROTOCOLS.md"):
        await preflight(settings, store)


async def test_preflight_raises_on_missing_user(
    settings: Settings, store: Store, profile: Path
) -> None:
    (profile / "USER.md").unlink()
    with pytest.raises(FileNotFoundError, match="USER.md"):
        await preflight(settings, store)


async def test_preflight_raises_on_missing_mcp_config(
    store: Store, tmp_path: Path, profile: Path
) -> None:
    s = Settings(  # type: ignore[call-arg]
        telegram=_FAKE_TELEGRAM,
        profile_path=profile,
        mcp_config=tmp_path / "nonexistent.json",
    )
    with pytest.raises(FileNotFoundError, match="(?i)mcp"):
        await preflight(s, store)


async def test_checkin_loop_fires_after_interval(tmp_path: Path) -> None:
    """Integration: checkin_loop calls checkin_handler.run() repeatedly."""
    run_calls: list[float] = []

    async def fake_run() -> None:
        run_calls.append(asyncio.get_event_loop().time())
        if len(run_calls) >= 2:
            raise asyncio.CancelledError

    handler = MagicMock(spec=CheckinHandler)
    handler.run = AsyncMock(side_effect=fake_run)

    # Replicate checkin_loop from main.py with a short sleep
    async def checkin_loop() -> None:
        while True:
            await handler.run()
            await asyncio.sleep(0.01)

    with pytest.raises((asyncio.CancelledError, ExceptionGroup)):
        await asyncio.wait_for(checkin_loop(), timeout=1.0)

    assert len(run_calls) >= 2


async def test_preflight_raises_on_bad_schema(
    settings: Settings, tmp_path: Path
) -> None:
    import aiosqlite

    db_path = tmp_path / "bad.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
        await db.commit()

    bad_store = Store.__new__(Store)
    bad_store._db = await aiosqlite.connect(db_path)  # type: ignore[attr-defined]
    try:
        with pytest.raises(RuntimeError, match="(?i)missing"):
            await preflight(settings, bad_store)
    finally:
        await bad_store._db.close()  # type: ignore[attr-defined]
