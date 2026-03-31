"""Tests for awfulclaw/location.py — timezone helpers and USER.md update."""

from __future__ import annotations

from pathlib import Path

import pytest
from awfulclaw.location import _update_user_timezone, _user_timezone


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_user_timezone_returns_empty_when_no_file() -> None:
    assert _user_timezone() == ""


def test_user_timezone_returns_empty_when_unknown() -> None:
    Path("memory").mkdir()
    Path("memory/USER.md").write_text("# User\nTimezone: unknown\n")
    assert _user_timezone() == ""


def test_user_timezone_returns_iana_name() -> None:
    Path("memory").mkdir()
    Path("memory/USER.md").write_text("# User\nTimezone: Europe/Berlin\n")
    assert _user_timezone() == "Europe/Berlin"


def test_user_timezone_ignores_trailing_comment() -> None:
    """'Timezone: Europe/Berlin (Germany)' → 'Europe/Berlin'"""
    Path("memory").mkdir()
    Path("memory/USER.md").write_text("# User\nTimezone: Europe/Berlin (Germany)\n")
    assert _user_timezone() == "Europe/Berlin"


def test_update_user_timezone_replaces_line() -> None:
    Path("memory").mkdir()
    Path("memory/USER.md").write_text("# User\nTimezone: unknown\nName: Charlie\n")
    _update_user_timezone("America/New_York")
    content = Path("memory/USER.md").read_text()
    assert "Timezone: America/New_York" in content
    assert "Timezone: unknown" not in content
    assert "Name: Charlie" in content


def test_update_user_timezone_no_op_when_no_file() -> None:
    # Should not raise even if USER.md doesn't exist
    _update_user_timezone("Europe/Berlin")


def test_update_user_timezone_appends_when_no_timezone_line() -> None:
    Path("memory").mkdir()
    Path("memory/USER.md").write_text("# User\nName: Charlie\n")
    _update_user_timezone("Europe/Berlin")
    content = Path("memory/USER.md").read_text()
    assert "Timezone: Europe/Berlin" in content
    assert "Name: Charlie" in content
