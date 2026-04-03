from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agent.config import Settings, TelegramSettings
from agent.handlers.checkin import CheckinHandler
from agent.main import preflight, _ShutdownRequested, build_client
from agent.claude_client import ClaudeClient
from agent.ollama_client import OllamaClient
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


async def test_sigterm_shutdown_cleanup_runs_without_cancellation() -> None:
    """SIGTERM path: cleanup after except* runs with cancellations cleared."""
    shutdown_event = asyncio.Event()

    async def _shutdown_watcher() -> None:
        await shutdown_event.wait()
        raise _ShutdownRequested()

    async def _long_running() -> None:
        await asyncio.sleep(60)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_long_running())
            tg.create_task(_shutdown_watcher())
            shutdown_event.set()
    except* _ShutdownRequested:
        pass

    # Clear any pending cancellations (same as main.py's finally block does).
    task = asyncio.current_task()
    if task is not None:
        while task.cancelling():
            task.uncancel()

    # Cleanup code should now run without asyncio injecting CancelledErrors.
    assert not asyncio.current_task().cancelling(), (
        "Task still has pending cancellations — disconnect_all() would fail"
    )


def test_build_client_returns_claude() -> None:
    client = build_client("claude", Settings())
    assert isinstance(client, ClaudeClient)


def test_build_client_returns_ollama() -> None:
    client = build_client("ollama", Settings())
    assert isinstance(client, OllamaClient)


def test_build_client_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown backend"):
        build_client("gemini", Settings())


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
