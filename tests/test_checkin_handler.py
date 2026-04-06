"""Tests for CheckinHandler."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.handlers.checkin import CheckinHandler, _warrants_attention


# --- unit tests for _warrants_attention ---

def test_warrants_attention_empty():
    assert _warrants_attention("") is False


def test_warrants_attention_whitespace():
    assert _warrants_attention("   ") is False


def test_warrants_attention_nothing_to_report():
    assert _warrants_attention("Nothing to report") is False


def test_warrants_attention_all_clear():
    assert _warrants_attention("All clear") is False


def test_warrants_attention_silent():
    assert _warrants_attention("Silent") is False


def test_warrants_attention_substantive_reply():
    assert _warrants_attention("The backup schedule failed last night.") is True


def test_warrants_attention_mixed_content():
    # starts with a silent phrase — still not warranted
    assert _warrants_attention("nothing to report today.") is False


def test_warrants_attention_question():
    assert _warrants_attention("Did you notice the disk usage is at 90%?") is True


# --- CheckinHandler tests ---

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.kv_get = AsyncMock(return_value=None)
    store.kv_set = AsyncMock()
    store.kv_delete = AsyncMock()
    return store


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.invoke = AsyncMock(return_value="Nothing to report")
    return agent


@pytest.fixture
def mock_bus():
    bus = MagicMock()
    bus.post = AsyncMock()
    return bus


@pytest.fixture
def mock_settings(tmp_path: Path):
    settings = MagicMock()
    settings.checkin_interval = 3600
    settings.idle_interval = 14400
    settings.profile_path = tmp_path
    checkin_file = tmp_path / "CHECKIN.md"
    checkin_file.write_text("Check everything and report if something needs attention.")
    return settings


@pytest.mark.asyncio
async def test_stays_silent_when_nothing_to_report(mock_agent, mock_bus, mock_store, mock_settings):
    mock_agent.invoke = AsyncMock(return_value="Nothing to report")
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_bus.post.assert_not_called()


@pytest.mark.asyncio
async def test_posts_when_warranted(mock_agent, mock_bus, mock_store, mock_settings):
    mock_agent.invoke = AsyncMock(return_value="Disk usage is at 95%, you should check.")
    mock_store.kv_get = AsyncMock(side_effect=lambda key: {
        "last_channel": "chan1",
        "last_sender": "user1",
    }.get(key))
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_bus.post.assert_called_once()


@pytest.mark.asyncio
async def test_respects_interval_skips_when_recent(mock_agent, mock_bus, mock_store, mock_settings):
    recent = str(time.time() - 100)  # only 100s ago, interval is 3600s
    mock_store.kv_get = AsyncMock(return_value=recent)
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_agent.invoke.assert_not_called()
    mock_bus.post.assert_not_called()


@pytest.mark.asyncio
async def test_runs_when_interval_elapsed(mock_agent, mock_bus, mock_store, mock_settings):
    old = str(time.time() - 7200)  # 2 hours ago, interval is 3600s
    mock_store.kv_get = AsyncMock(return_value=old)
    mock_agent.invoke = AsyncMock(return_value="Something needs attention here.")

    async def kv_get_side(key: str):
        if key == "last_checkin":
            return old
        if key == "last_channel":
            return "chan1"
        if key == "last_sender":
            return "user1"
        return None

    mock_store.kv_get = AsyncMock(side_effect=kv_get_side)
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_agent.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_updates_last_checkin_timestamp(mock_agent, mock_bus, mock_store, mock_settings):
    mock_agent.invoke = AsyncMock(return_value="Nothing to report")
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_store.kv_set.assert_called_once()
    key, val = mock_store.kv_set.call_args[0]
    assert key == "last_checkin"
    assert float(val) == pytest.approx(time.time(), abs=5)


@pytest.mark.asyncio
async def test_no_post_when_no_channel(mock_agent, mock_bus, mock_store, mock_settings):
    mock_agent.invoke = AsyncMock(return_value="Disk is full!")
    mock_store.kv_get = AsyncMock(return_value=None)  # no last_channel/last_sender
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_bus.post.assert_not_called()


# ---------------------------------------------------------------------------
# Email triage integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skips_model_when_only_routine_emails(mock_agent, mock_bus, mock_store, mock_settings):
    triage = {"newsletters": ["Sale!"], "routine": ["Parcel delivered"], "escalate": []}

    async def kv_get_side(key: str):
        if key == "email_triage":
            return json.dumps(triage)
        if key == "last_channel":
            return "chan1"
        if key == "last_sender":
            return "user1"
        return None

    mock_store.kv_get = AsyncMock(side_effect=kv_get_side)
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_agent.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_invokes_model_when_escalated_emails(mock_agent, mock_bus, mock_store, mock_settings):
    triage = {
        "newsletters": [],
        "routine": [],
        "escalate": [{"uid": "1", "from": "boss@co.com", "subject": "Urgent", "summary": "Needs reply"}],
    }

    async def kv_get_side(key: str):
        if key == "email_triage":
            return json.dumps(triage)
        if key == "last_channel":
            return "chan1"
        if key == "last_sender":
            return "user1"
        return None

    mock_store.kv_get = AsyncMock(side_effect=kv_get_side)
    mock_agent.invoke = AsyncMock(return_value="You have an urgent email from boss.")
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_agent.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_clears_triage_results_after_consuming(mock_agent, mock_bus, mock_store, mock_settings):
    triage = {"newsletters": ["A"], "routine": ["B"], "escalate": []}

    async def kv_get_side(key: str):
        if key == "email_triage":
            return json.dumps(triage)
        return None

    mock_store.kv_get = AsyncMock(side_effect=kv_get_side)
    mock_store.kv_delete = AsyncMock()
    handler = CheckinHandler(mock_agent, mock_bus, mock_store, mock_settings)
    await handler.run()
    mock_store.kv_delete.assert_called_once_with("email_triage")
