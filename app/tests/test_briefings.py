"""Tests for briefings.py — daily briefing schedule auto-creation and startup prompt."""

from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path

import pytest
from awfulclaw.briefings import (
    BRIEFING_PROMPT,
    ensure_daily_briefing,
    get_startup_prompt,
)
from awfulclaw.scheduler import load_schedules


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


# --- ensure_daily_briefing ---


def test_daily_briefing_created_with_correct_cron() -> None:
    ensure_daily_briefing(time(8, 0))
    schedules = load_schedules()
    daily = [s for s in schedules if s.name == "daily_briefing"]
    assert len(daily) == 1
    assert daily[0].cron == "0 8 * * *"
    assert daily[0].prompt == BRIEFING_PROMPT
    assert daily[0].fire_at is None


def test_daily_briefing_custom_time() -> None:
    ensure_daily_briefing(time(7, 30))
    schedules = load_schedules()
    daily = [s for s in schedules if s.name == "daily_briefing"]
    assert daily[0].cron == "30 7 * * *"


def test_daily_briefing_idempotent() -> None:
    ensure_daily_briefing(time(8, 0))
    ensure_daily_briefing(time(8, 0))
    schedules = load_schedules()
    assert len([s for s in schedules if s.name == "daily_briefing"]) == 1


def test_daily_briefing_not_created_when_already_exists() -> None:
    """If a daily_briefing schedule already exists (e.g. user-customised), leave it alone."""
    ensure_daily_briefing(time(8, 0))
    first = [s for s in load_schedules() if s.name == "daily_briefing"][0]
    original_id = first.id

    ensure_daily_briefing(time(9, 0))  # different time — should be ignored
    schedules = load_schedules()
    daily = [s for s in schedules if s.name == "daily_briefing"]
    assert len(daily) == 1
    assert daily[0].id == original_id
    assert daily[0].cron == "0 8 * * *"  # unchanged


def test_daily_briefing_fires_on_cron() -> None:
    """Briefing schedule fires when its cron time arrives."""
    from awfulclaw.scheduler import Schedule, get_due

    # Build a schedule with known created_at so the cron anchor is in the past
    s = Schedule.create(
        name="daily_briefing",
        cron="0 8 * * *",
        prompt=BRIEFING_PROMPT,
    )
    s.created_at = datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc)

    # 9am the next day — the 8am slot is due
    now = datetime(2026, 3, 30, 9, 0, tzinfo=timezone.utc)
    due = get_due([s], now)
    assert s in due



def test_startup_prompt_includes_progress_note(tmp_path: Path) -> None:
    """get_startup_prompt embeds existing progress.md content."""
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "progress.md").write_text("Previous note here.")
    prompt = get_startup_prompt()
    assert "Previous note here." in prompt


def test_startup_prompt_no_progress_note(tmp_path: Path) -> None:
    """get_startup_prompt works when no progress.md exists."""
    prompt = get_startup_prompt()
    assert "previous progress note" not in prompt
    assert "orient yourself" in prompt
