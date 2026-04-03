from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent.config import Settings, TelegramSettings
from agent.main import preflight
from agent.store import Store


@pytest.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


@pytest.fixture
def agent_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "agent_config"
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
def settings(tmp_path: Path, agent_config: Path, mcp_config: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        telegram=_FAKE_TELEGRAM,
        agent_config_path=agent_config,
        mcp_config=mcp_config,
    )


async def test_preflight_passes_with_valid_setup(
    settings: Settings, store: Store
) -> None:
    await preflight(settings, store)  # must not raise


async def test_preflight_raises_on_missing_personality(
    settings: Settings, store: Store, agent_config: Path
) -> None:
    (agent_config / "PERSONALITY.md").unlink()
    with pytest.raises(FileNotFoundError, match="PERSONALITY.md"):
        await preflight(settings, store)


async def test_preflight_raises_on_missing_protocols(
    settings: Settings, store: Store, agent_config: Path
) -> None:
    (agent_config / "PROTOCOLS.md").unlink()
    with pytest.raises(FileNotFoundError, match="PROTOCOLS.md"):
        await preflight(settings, store)


async def test_preflight_raises_on_missing_user(
    settings: Settings, store: Store, agent_config: Path
) -> None:
    (agent_config / "USER.md").unlink()
    with pytest.raises(FileNotFoundError, match="USER.md"):
        await preflight(settings, store)


async def test_preflight_raises_on_missing_mcp_config(
    store: Store, tmp_path: Path, agent_config: Path
) -> None:
    s = Settings(  # type: ignore[call-arg]
        telegram=_FAKE_TELEGRAM,
        agent_config_path=agent_config,
        mcp_config=tmp_path / "nonexistent.json",
    )
    with pytest.raises(FileNotFoundError, match="(?i)mcp"):
        await preflight(s, store)


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
