"""Tests for _handle_slash_command in loop.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from awfulclaw.loop import handle_slash_command as _handle_slash_command
from awfulclaw.scheduler import Schedule


@pytest.fixture()
def mem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change CWD to tmp_path and create memory subdirs."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory" / "tasks").mkdir(parents=True)
    (tmp_path / "memory" / "skills").mkdir(parents=True)
    return tmp_path / "memory"


# ---------------------------------------------------------------------------
# /tasks
# ---------------------------------------------------------------------------


def test_tasks_returns_open_items(mem: Path) -> None:
    (mem / "tasks" / "work.md").write_text(
        "# Work\n- [ ] Buy milk\n- [x] Done thing\n- [ ] Fix bug\n"
    )
    result = _handle_slash_command("/tasks")
    assert result is not None
    assert "- [ ] Buy milk" in result
    assert "- [ ] Fix bug" in result
    assert "- [x] Done thing" not in result


def test_tasks_no_open_items(mem: Path) -> None:
    (mem / "tasks" / "done.md").write_text("- [x] All done\n")
    result = _handle_slash_command("/tasks")
    assert result == "No open tasks."


def test_tasks_empty_dir(mem: Path) -> None:
    result = _handle_slash_command("/tasks")
    assert result == "No open tasks."


# ---------------------------------------------------------------------------
# /skills
# ---------------------------------------------------------------------------


def test_skills_returns_content(mem: Path) -> None:
    (mem / "skills" / "search.md").write_text("Search the web using DuckDuckGo.")
    result = _handle_slash_command("/skills")
    assert result is not None
    assert "search" in result
    assert "Search the web using DuckDuckGo." in result


def test_skills_empty(mem: Path) -> None:
    result = _handle_slash_command("/skills")
    assert result == "No skills saved."


# ---------------------------------------------------------------------------
# /schedules
# ---------------------------------------------------------------------------


def test_schedules_returns_list() -> None:
    sched = Schedule.create(name="morning", cron="0 8 * * *", prompt="Good morning check")
    with patch("awfulclaw.loop.scheduler.load_schedules", return_value=[sched]):
        result = _handle_slash_command("/schedules")
    assert result is not None
    assert "morning" in result
    assert "0 8 * * *" in result
    assert "Good morning check" in result


def test_schedules_empty() -> None:
    with patch("awfulclaw.loop.scheduler.load_schedules", return_value=[]):
        result = _handle_slash_command("/schedules")
    assert result == "No schedules."


def test_schedules_prompt_truncated() -> None:
    long_prompt = "A" * 100
    sched = Schedule.create(name="test", cron="* * * * *", prompt=long_prompt)
    with patch("awfulclaw.loop.scheduler.load_schedules", return_value=[sched]):
        result = _handle_slash_command("/schedules")
    assert result is not None
    assert "…" in result


# ---------------------------------------------------------------------------
# unknown command
# ---------------------------------------------------------------------------


def test_unknown_command_lists_available() -> None:
    result = _handle_slash_command("/foo")
    assert result is not None
    assert "/tasks" in result
    assert "/skills" in result
    assert "/schedules" in result


# ---------------------------------------------------------------------------
# non-command returns None
# ---------------------------------------------------------------------------


def test_non_command_returns_none() -> None:
    assert _handle_slash_command("hello world") is None
    assert _handle_slash_command("") is None
