from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.backend_manager import BackendManager
from agent.connectors import OutboundEvent

MCP_CONFIG = Path("/tmp/mcp.json")


def _make_client(*, fail: bool = False, response: str = "ok") -> MagicMock:
    client = MagicMock()
    if fail:
        client.complete = AsyncMock(side_effect=RuntimeError("backend error"))
    else:
        client.complete = AsyncMock(return_value=response)
    client.health_check = AsyncMock(return_value=not fail)
    return client


def _make_manager(
    primary: MagicMock,
    fallback: MagicMock | None = None,
    *,
    threshold: int = 3,
    locked: bool = False,
    bus: MagicMock | None = None,
    notify_channel: tuple[str, str] | None = None,
) -> BackendManager:
    return BackendManager(
        primary=primary,
        fallback=fallback,
        failure_threshold=threshold,
        probe_interval=1,
        bus=bus,
        notify_channel=notify_channel,
        locked=locked,
    )


async def test_passes_through_to_primary() -> None:
    primary = _make_client(response="from primary")
    mgr = _make_manager(primary)
    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "from primary"
    primary.complete.assert_called_once()


async def test_resets_failure_count_on_primary_success() -> None:
    primary = _make_client()
    fallback = _make_client()
    mgr = _make_manager(primary, fallback, threshold=3)
    # two failures then a success — should never switch
    primary.complete = AsyncMock(side_effect=[
        RuntimeError("err"), RuntimeError("err"), "ok"
    ])
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "ok"
    fallback.complete.assert_not_called()


async def test_switches_to_fallback_after_threshold() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="from fallback")
    bus = MagicMock()
    bus.post = AsyncMock()
    mgr = _make_manager(
        primary, fallback, threshold=2, bus=bus, notify_channel=("telegram", "123")
    )

    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    fallback.complete.assert_not_called()

    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "from fallback"
    fallback.complete.assert_called_once()
    bus.post.assert_called_once()
    event: OutboundEvent = bus.post.call_args[0][0]
    assert "Ollama" in event.message.text


async def test_locked_never_switches() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="should not be called")
    mgr = _make_manager(primary, fallback, threshold=1, locked=True)

    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    fallback.complete.assert_not_called()


async def test_switch_to_primary_in_automatic_mode() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="fallback")
    mgr = _make_manager(primary, fallback, threshold=1)

    await mgr.complete("q", "sys", MCP_CONFIG, [])  # triggers switch

    primary.complete = AsyncMock(return_value="primary restored")
    await mgr.switch_to_primary()
    result = await mgr.complete("q", "sys", MCP_CONFIG, [])
    assert result == "primary restored"


async def test_switch_to_primary_is_noop_when_locked() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="fallback")
    mgr = _make_manager(primary, fallback, threshold=1, locked=True)

    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    await mgr.switch_to_primary()  # no-op
    with pytest.raises(RuntimeError):
        await mgr.complete("q", "sys", MCP_CONFIG, [])
    fallback.complete.assert_not_called()


async def test_check_and_notify_sends_recovery_message() -> None:
    primary = _make_client(fail=True)
    fallback = _make_client(response="fallback")
    bus = MagicMock()
    bus.post = AsyncMock()
    mgr = _make_manager(
        primary, fallback, threshold=1, bus=bus, notify_channel=("telegram", "123")
    )

    await mgr.complete("q", "sys", MCP_CONFIG, [])  # triggers switch; post called once

    primary.health_check = AsyncMock(return_value=True)
    await mgr._check_and_notify()

    assert bus.post.call_count == 2
    recovery_event: OutboundEvent = bus.post.call_args[0][0]
    assert "/use-primary" in recovery_event.message.text


async def test_check_and_notify_silent_when_not_on_fallback() -> None:
    primary = _make_client()
    fallback = _make_client()
    bus = MagicMock()
    bus.post = AsyncMock()
    mgr = _make_manager(primary, fallback, bus=bus, notify_channel=("telegram", "123"))

    await mgr._check_and_notify()
    bus.post.assert_not_called()
