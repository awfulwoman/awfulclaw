"""Tests for the schedule module."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory").mkdir()


def _dispatch(tag: str) -> str:
    from awfulclaw.modules.schedule._schedule import ScheduleModule

    mod = ScheduleModule()
    skill_tag = mod.skill_tags[0]
    m = skill_tag.pattern.search(tag)
    assert m is not None, f"Tag did not match: {tag!r}"
    return mod.dispatch(m, [], "")


def test_create_cron_schedule() -> None:
    result = _dispatch(
        '<skill:schedule action="create" name="test" cron="0 8 * * *">do something</skill:schedule>'
    )
    assert "created" in result.lower()
    assert "test" in result

    import awfulclaw.scheduler as sched

    schedules = sched.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].name == "test"
    assert schedules[0].cron == "0 8 * * *"
    assert schedules[0].prompt == "do something"


def test_create_at_schedule() -> None:
    result = _dispatch(
        '<skill:schedule action="create" name="reminder" at="2099-12-31T09:00:00Z">'
        "buy milk</skill:schedule>"
    )
    assert "created" in result.lower()

    import awfulclaw.scheduler as sched

    schedules = sched.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].fire_at is not None


def test_update_existing_schedule() -> None:
    _dispatch('<skill:schedule action="create" name="test" cron="0 8 * * *">v1</skill:schedule>')
    result = _dispatch(
        '<skill:schedule action="create" name="test" cron="0 9 * * *">v2</skill:schedule>'
    )
    assert "updated" in result.lower()

    import awfulclaw.scheduler as sched

    schedules = sched.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].cron == "0 9 * * *"
    assert schedules[0].prompt == "v2"


def test_delete_schedule() -> None:
    _dispatch('<skill:schedule action="create" name="todelete" cron="* * * * *">x</skill:schedule>')
    result = _dispatch('<skill:schedule action="delete" name="todelete"/>')
    assert "deleted" in result.lower()

    import awfulclaw.scheduler as sched

    schedules = sched.load_schedules()
    assert len(schedules) == 0


def test_delete_nonexistent_schedule() -> None:
    result = _dispatch('<skill:schedule action="delete" name="ghost"/>')
    assert "not found" in result.lower()


def test_invalid_cron_returns_error() -> None:
    result = _dispatch(
        '<skill:schedule action="create" name="bad" cron="not-a-cron">x</skill:schedule>'
    )
    assert "error" in result.lower() or "invalid" in result.lower()


def test_invalid_at_returns_error() -> None:
    result = _dispatch(
        '<skill:schedule action="create" name="bad" at="not-a-datetime">x</skill:schedule>'
    )
    assert "error" in result.lower() or "invalid" in result.lower()


def test_should_wake_true_on_success(tmp_path: Path) -> None:
    from awfulclaw.modules.schedule._schedule import should_wake

    script = tmp_path / "check.sh"
    script.write_text("#!/bin/sh\necho '{\"wakeAgent\": true}'")
    script.chmod(0o755)
    assert should_wake(str(script)) is True


def test_should_wake_false_when_suppressed(tmp_path: Path) -> None:
    from awfulclaw.modules.schedule._schedule import should_wake

    script = tmp_path / "check.sh"
    script.write_text("#!/bin/sh\necho '{\"wakeAgent\": false}'")
    script.chmod(0o755)
    assert should_wake(str(script)) is False


def test_should_wake_true_on_error() -> None:
    from awfulclaw.modules.schedule._schedule import should_wake

    assert should_wake("nonexistent_command_xyz") is True


def test_create_module() -> None:
    from awfulclaw.modules.schedule import create_module

    mod = create_module()
    assert mod.name == "schedule"
    assert mod.is_available() is True
