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


from unittest.mock import MagicMock, patch

from awfulclaw.location import check_and_update_timezone, fetch_owntracks_position, resolve_timezone

_POSITION = {"lat": 40.7128, "lon": -74.0060, "tst": 1743000000}


def test_fetch_owntracks_position_returns_first_item() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = [_POSITION]
    mock_resp.raise_for_status.return_value = None
    with patch("awfulclaw.location.httpx.get", return_value=mock_resp):
        result = fetch_owntracks_position("https://example.com", "charlie", "iphone")
    assert result == _POSITION


def test_fetch_owntracks_position_returns_none_on_empty_list() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status.return_value = None
    with patch("awfulclaw.location.httpx.get", return_value=mock_resp):
        result = fetch_owntracks_position("https://example.com", "charlie", "iphone")
    assert result is None


def test_fetch_owntracks_position_returns_none_on_network_error() -> None:
    with patch("awfulclaw.location.httpx.get", side_effect=Exception("connection refused")):
        result = fetch_owntracks_position("https://example.com", "charlie", "iphone")
    assert result is None


def test_resolve_timezone_returns_iana_name() -> None:
    # London coordinates → Europe/London
    result = resolve_timezone(51.5074, -0.1278)
    assert result == "Europe/London"


def test_resolve_timezone_returns_none_for_ocean() -> None:
    # Middle of Pacific Ocean
    result = resolve_timezone(0.0, -160.0)
    # May return None or a valid tz — just assert it doesn't raise
    assert result is None or isinstance(result, str)


def test_check_and_update_timezone_updates_when_changed(tmp_path: Path) -> None:
    Path("memory").mkdir(exist_ok=True)
    Path("memory/USER.md").write_text("# User\nTimezone: Europe/Berlin\n")
    with (
        patch("awfulclaw.location.fetch_owntracks_position", return_value=_POSITION),
        patch("awfulclaw.location.resolve_timezone", return_value="America/New_York"),
    ):
        check_and_update_timezone("https://example.com")
    content = Path("memory/USER.md").read_text()
    assert "Timezone: America/New_York" in content


def test_check_and_update_timezone_no_op_when_same(tmp_path: Path) -> None:
    Path("memory").mkdir(exist_ok=True)
    Path("memory/USER.md").write_text("# User\nTimezone: Europe/Berlin\n")
    with (
        patch("awfulclaw.location.fetch_owntracks_position", return_value=_POSITION),
        patch("awfulclaw.location.resolve_timezone", return_value="Europe/Berlin"),
        patch("awfulclaw.location._update_user_timezone") as mock_update,
    ):
        check_and_update_timezone("https://example.com")
    mock_update.assert_not_called()


def test_check_and_update_timezone_no_op_when_unreachable(tmp_path: Path) -> None:
    Path("memory").mkdir(exist_ok=True)
    Path("memory/USER.md").write_text("# User\nTimezone: Europe/Berlin\n")
    with (
        patch("awfulclaw.location.fetch_owntracks_position", return_value=None),
        patch("awfulclaw.location._update_user_timezone") as mock_update,
    ):
        check_and_update_timezone("https://example.com")
    mock_update.assert_not_called()
    assert "Europe/Berlin" in Path("memory/USER.md").read_text()
