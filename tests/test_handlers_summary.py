from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.handlers.summary import SummaryHandler, _SUMMARY_INTERVAL


def _make_handler(tmp_path: Path, invoke_side_effect=None):
    agent = MagicMock()
    agent.invoke = AsyncMock(side_effect=invoke_side_effect or (lambda p: "summary text"))
    store = AsyncMock()
    store.kv_get = AsyncMock(return_value=None)
    store.kv_set = AsyncMock()
    return SummaryHandler(agent, store, tmp_path), agent, store


@pytest.mark.asyncio
async def test_run_writes_three_summary_files(tmp_path: Path) -> None:
    handler, agent, store = _make_handler(tmp_path)
    await handler.run()

    info_dir = tmp_path / "info"
    assert (info_dir / "user.md").is_file()
    assert (info_dir / "personality.md").is_file()
    assert (info_dir / "protocols.md").is_file()
    assert agent.invoke.call_count == 3


@pytest.mark.asyncio
async def test_run_skips_when_called_recently(tmp_path: Path) -> None:
    import time
    handler, agent, store = _make_handler(tmp_path)
    store.kv_get = AsyncMock(return_value=str(time.time()))  # just ran
    await handler.run()
    agent.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_run_proceeds_after_interval(tmp_path: Path) -> None:
    import time
    handler, agent, store = _make_handler(tmp_path)
    store.kv_get = AsyncMock(return_value=str(time.time() - _SUMMARY_INTERVAL - 1))
    await handler.run()
    assert agent.invoke.call_count == 3


@pytest.mark.asyncio
async def test_summary_content_is_written(tmp_path: Path) -> None:
    handler, agent, _ = _make_handler(
        tmp_path,
        invoke_side_effect=lambda p: f"content for {p[:10]}"
    )
    await handler.run()
    text = (tmp_path / "info" / "user.md").read_text(encoding="utf-8")
    assert text.startswith("content for")


@pytest.mark.asyncio
async def test_partial_failure_does_not_crash(tmp_path: Path) -> None:
    call_count = 0

    async def flaky(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient error")
        return "ok"

    handler, agent, store = _make_handler(tmp_path)
    agent.invoke = AsyncMock(side_effect=flaky)
    # Should not raise even if one invoke fails
    await handler.run()
    # Two of the three files should have been written
    written = list((tmp_path / "info").glob("*.md"))
    assert len(written) == 2
