"""Tests for scripts/import_schedules.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import import_schedules  # noqa: E402

SAMPLE_SCHEDULES = [
    {
        "name": "daily-briefing",
        "cron": "0 8 * * *",
        "prompt": "Run the daily-briefing skill.",
        "silent": False,
        "tz": "Europe/Berlin",
    },
    {
        "name": "weekly-review",
        "cron": "0 18 * * 5",
        "prompt": "Do a weekly review.",
        "silent": True,
        "tz": "Europe/Berlin",
    },
]


async def _store(tmp: Path):
    from agent.store import Store

    return await Store.connect(tmp / "test.db")


@pytest.fixture
def schedules_json(tmp_path: Path) -> Path:
    p = tmp_path / "schedules.json"
    p.write_text(json.dumps(SAMPLE_SCHEDULES))
    return p


@pytest.mark.asyncio
async def test_parse_and_insert(schedules_json: Path, tmp_path: Path):
    """Parses legacy format and inserts schedules into DB."""
    await import_schedules.run(schedules_json, db_path=tmp_path / "test.db")

    store = await _store(tmp_path)
    try:
        schedules = await store.list_schedules()
        names = {s.name for s in schedules}
        assert "daily-briefing" in names
        assert "weekly-review" in names
        assert len(schedules) == 2

        briefing = next(s for s in schedules if s.name == "daily-briefing")
        assert briefing.cron == "0 8 * * *"
        assert briefing.prompt == "Run the daily-briefing skill."
        assert briefing.silent is False
        assert briefing.tz == "Europe/Berlin"

        review = next(s for s in schedules if s.name == "weekly-review")
        assert review.silent is True
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_skip_duplicate(schedules_json: Path, tmp_path: Path):
    """Re-running import skips existing schedules by name."""
    db = tmp_path / "test.db"
    await import_schedules.run(schedules_json, db_path=db)
    imported, skipped = await import_schedules.run(schedules_json, db_path=db)
    assert imported == 0
    assert skipped == 2

    store = await _store(tmp_path)
    try:
        assert len(await store.list_schedules()) == 2
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_partial_duplicate(tmp_path: Path):
    """Only new schedules are inserted when some already exist."""
    db = tmp_path / "test.db"

    p1 = tmp_path / "first.json"
    p1.write_text(json.dumps([SAMPLE_SCHEDULES[0]]))
    await import_schedules.run(p1, db_path=db)

    both = tmp_path / "both.json"
    both.write_text(json.dumps(SAMPLE_SCHEDULES))
    imported, skipped = await import_schedules.run(both, db_path=db)
    assert imported == 1
    assert skipped == 1


@pytest.mark.asyncio
async def test_optional_fields_defaulted(tmp_path: Path):
    """Schedules without optional fields get sensible defaults."""
    db = tmp_path / "test.db"
    minimal = [{"name": "ping", "prompt": "Say hello.", "cron": "* * * * *"}]
    p = tmp_path / "min.json"
    p.write_text(json.dumps(minimal))
    await import_schedules.run(p, db_path=db)

    store = await _store(tmp_path)
    try:
        schedules = await store.list_schedules()
        assert len(schedules) == 1
        s = schedules[0]
        assert s.name == "ping"
        assert s.silent is False
        assert s.tz == ""
        assert s.id  # uuid generated
        assert s.created_at
        assert s.last_run is None
        assert s.fire_at is None
    finally:
        await store.close()
