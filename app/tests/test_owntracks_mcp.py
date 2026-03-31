"""Tests for the OwnTracks MCP server."""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def set_owntracks_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNTRACKS_URL", "https://example.com")


def test_get_location_happy_path() -> None:
    from awfulclaw_mcp.owntracks import owntracks_get_location

    with (
        patch(
            "awfulclaw_mcp.owntracks.fetch_owntracks_position",
            return_value={"lat": 51.5074, "lon": -0.1278, "tst": 1743000000},
        ),
        patch("awfulclaw_mcp.owntracks.resolve_timezone", return_value="Europe/London"),
        patch("awfulclaw_mcp.owntracks.reverse_geocode", return_value="London, United Kingdom"),
    ):
        result = owntracks_get_location()

    assert "London, United Kingdom" in result
    assert "Europe/London" in result
    assert "ago" in result


def test_get_location_owntracks_unreachable() -> None:
    from awfulclaw_mcp.owntracks import owntracks_get_location

    with patch("awfulclaw_mcp.owntracks.fetch_owntracks_position", return_value=None):
        result = owntracks_get_location()

    assert "error" in result.lower()


def test_get_location_nominatim_unreachable() -> None:
    """If Nominatim fails, still return timezone without city."""
    from awfulclaw_mcp.owntracks import owntracks_get_location

    with (
        patch(
            "awfulclaw_mcp.owntracks.fetch_owntracks_position",
            return_value={"lat": 51.5074, "lon": -0.1278, "tst": 1743000000},
        ),
        patch("awfulclaw_mcp.owntracks.resolve_timezone", return_value="Europe/London"),
        patch("awfulclaw_mcp.owntracks.reverse_geocode", return_value=None),
    ):
        result = owntracks_get_location()

    assert "Europe/London" in result
    assert "error" not in result.lower()


def test_get_location_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OWNTRACKS_URL", raising=False)
    # Re-import to pick up missing env var
    import awfulclaw_mcp.owntracks as mod
    importlib.reload(mod)
    result = mod.owntracks_get_location()
    assert "OWNTRACKS_URL" in result


def test_get_location_malformed_response() -> None:
    from awfulclaw_mcp.owntracks import owntracks_get_location

    with patch(
        "awfulclaw_mcp.owntracks.fetch_owntracks_position",
        return_value={"_type": "location"},  # missing lat/lon
    ):
        result = owntracks_get_location()

    assert "error" in result.lower()
