"""Unit tests for agent/mcp/owntracks.py — mocked aiosqlite and timezonefinder."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.mcp.owntracks as owntracks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _location_payload(lat: float = 48.8566, lon: float = 2.3522) -> str:
    return json.dumps({"_type": "location", "lat": lat, "lon": lon, "acc": 10, "batt": 80})


def _mock_kv_set() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# Tests: valid location payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owntracks_update_writes_lat_lon_timezone() -> None:
    kv_calls: list[tuple[str, str]] = []

    async def fake_kv_set(key: str, value: str) -> None:
        kv_calls.append((key, value))

    with (
        patch("agent.mcp.owntracks._kv_set", side_effect=fake_kv_set),
        patch("agent.mcp.owntracks._timezone_from_coords", return_value="Europe/Paris"),
    ):
        result = await owntracks.owntracks_update(_location_payload(48.8566, 2.3522))

    assert "48.8566" in result
    assert "2.3522" in result
    assert "Europe/Paris" in result

    keys_written = {k for k, _ in kv_calls}
    assert "user_lat" in keys_written
    assert "user_lon" in keys_written
    assert "user_timezone" in keys_written


@pytest.mark.asyncio
async def test_owntracks_update_writes_correct_values() -> None:
    kv: dict[str, str] = {}

    async def fake_kv_set(key: str, value: str) -> None:
        kv[key] = value

    with (
        patch("agent.mcp.owntracks._kv_set", side_effect=fake_kv_set),
        patch("agent.mcp.owntracks._timezone_from_coords", return_value="Europe/Paris"),
    ):
        await owntracks.owntracks_update(_location_payload(48.8566, 2.3522))

    assert kv["user_lat"] == "48.8566"
    assert kv["user_lon"] == "2.3522"
    assert kv["user_timezone"] == "Europe/Paris"


@pytest.mark.asyncio
async def test_owntracks_update_no_timezone_when_finder_unavailable() -> None:
    kv: dict[str, str] = {}

    async def fake_kv_set(key: str, value: str) -> None:
        kv[key] = value

    with (
        patch("agent.mcp.owntracks._kv_set", side_effect=fake_kv_set),
        patch("agent.mcp.owntracks._timezone_from_coords", return_value=None),
    ):
        result = await owntracks.owntracks_update(_location_payload(48.8566, 2.3522))

    assert "user_timezone" not in kv
    assert "timezone not derived" in result


# ---------------------------------------------------------------------------
# Tests: untrusted content framing is NOT needed (read-only parsing)
# Tests: error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owntracks_update_invalid_json() -> None:
    result = await owntracks.owntracks_update("not json {{{")
    assert result.startswith("Error: invalid JSON")


@pytest.mark.asyncio
async def test_owntracks_update_non_object_payload() -> None:
    result = await owntracks.owntracks_update(json.dumps([1, 2, 3]))
    assert "JSON object" in result


@pytest.mark.asyncio
async def test_owntracks_update_wrong_type() -> None:
    payload = json.dumps({"_type": "transition", "lat": 48.8, "lon": 2.3})
    result = await owntracks.owntracks_update(payload)
    assert "Ignored" in result
    assert "transition" in result


@pytest.mark.asyncio
async def test_owntracks_update_missing_lat() -> None:
    payload = json.dumps({"_type": "location", "lon": 2.3522})
    result = await owntracks.owntracks_update(payload)
    assert "missing lat or lon" in result


@pytest.mark.asyncio
async def test_owntracks_update_missing_lon() -> None:
    payload = json.dumps({"_type": "location", "lat": 48.8566})
    result = await owntracks.owntracks_update(payload)
    assert "missing lat or lon" in result


@pytest.mark.asyncio
async def test_owntracks_update_non_numeric_coords() -> None:
    payload = json.dumps({"_type": "location", "lat": "north", "lon": 2.35})
    result = await owntracks.owntracks_update(payload)
    assert "numeric" in result
