"""Unit tests for agent/mcp/weather.py — uses mocked httpx and kv store."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.mcp.weather as weather


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_current_response(
    temp: float = 15.0,
    feels: float = 13.0,
    precip: float = 0.0,
    code: int = 1,
    wind: float = 10.0,
    humidity: int = 60,
) -> dict[str, Any]:
    return {
        "current": {
            "temperature_2m": temp,
            "apparent_temperature": feels,
            "precipitation": precip,
            "weathercode": code,
            "wind_speed_10m": wind,
            "relative_humidity_2m": humidity,
        },
        "current_units": {
            "temperature_2m": "°C",
            "apparent_temperature": "°C",
            "precipitation": "mm",
            "wind_speed_10m": "km/h",
        },
    }


def _make_forecast_response(days: int = 3) -> dict[str, Any]:
    dates = [f"2026-04-0{i + 1}" for i in range(days)]
    return {
        "daily": {
            "time": dates,
            "weathercode": [1, 61, 3][:days],
            "temperature_2m_max": [18.0, 14.0, 12.0][:days],
            "temperature_2m_min": [8.0, 10.0, 6.0][:days],
            "precipitation_sum": [0.0, 5.2, 0.0][:days],
            "wind_speed_10m_max": [15.0, 25.0, 10.0][:days],
        },
        "daily_units": {
            "temperature_2m_max": "°C",
            "temperature_2m_min": "°C",
            "precipitation_sum": "mm",
            "wind_speed_10m_max": "km/h",
        },
    }


def _mock_httpx(data: dict[str, Any]) -> MagicMock:
    """Return a mock httpx.AsyncClient context manager returning data."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = data

    client = MagicMock()
    client.get = AsyncMock(return_value=resp)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Tests: weather_current
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weather_current_explicit_coords() -> None:
    data = _make_current_response(temp=20.0, feels=18.0, code=0, wind=5.0, humidity=50)
    with patch("httpx.AsyncClient", return_value=_mock_httpx(data)):
        result = await weather.weather_current(lat=48.85, lon=2.35)

    assert "clear sky" in result
    assert "20" in result
    assert "18" in result
    assert "50%" in result
    assert "5" in result


@pytest.mark.asyncio
async def test_weather_current_with_precipitation() -> None:
    data = _make_current_response(temp=10.0, feels=8.0, code=63, precip=3.5, wind=20.0, humidity=90)
    with patch("httpx.AsyncClient", return_value=_mock_httpx(data)):
        result = await weather.weather_current(lat=51.5, lon=-0.1)

    assert "moderate rain" in result
    assert "3.5" in result
    assert "precipitation" in result


@pytest.mark.asyncio
async def test_weather_current_falls_back_to_kv() -> None:
    data = _make_current_response()
    with (
        patch("agent.mcp.weather._kv_get", new=AsyncMock(side_effect=lambda k: "48.85" if k == "user_lat" else "2.35")),
        patch("httpx.AsyncClient", return_value=_mock_httpx(data)) as mock_client_cls,
    ):
        result = await weather.weather_current()

    assert "mainly clear" in result
    # Verify coordinates were passed correctly
    call_kwargs = mock_client_cls.return_value.__aenter__.return_value.get.call_args
    params = call_kwargs[1]["params"]
    assert params["latitude"] == 48.85
    assert params["longitude"] == 2.35


@pytest.mark.asyncio
async def test_weather_current_unknown_wmo_code() -> None:
    data = _make_current_response(code=42)
    with patch("httpx.AsyncClient", return_value=_mock_httpx(data)):
        result = await weather.weather_current(lat=0.0, lon=0.0)

    assert "weather code 42" in result


# ---------------------------------------------------------------------------
# Tests: weather_forecast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weather_forecast_three_days() -> None:
    data = _make_forecast_response(days=3)
    with patch("httpx.AsyncClient", return_value=_mock_httpx(data)):
        result = await weather.weather_forecast(lat=48.85, lon=2.35, days=3)

    lines = result.strip().splitlines()
    assert len(lines) == 3
    assert "2026-04-01" in lines[0]
    assert "mainly clear" in lines[0]
    assert "8" in lines[0]  # low temp
    assert "18" in lines[0]  # high temp
    # Day 2 has rain
    assert "5.2mm" in lines[1]
    assert "light rain" in lines[1]


@pytest.mark.asyncio
async def test_weather_forecast_clamps_days() -> None:
    data = _make_forecast_response(days=3)
    with patch("httpx.AsyncClient", return_value=_mock_httpx(data)) as mock_client_cls:
        # 10 should be clamped to 7
        await weather.weather_forecast(lat=0.0, lon=0.0, days=10)

    call_kwargs = mock_client_cls.return_value.__aenter__.return_value.get.call_args
    params = call_kwargs[1]["params"]
    assert params["forecast_days"] == 7


@pytest.mark.asyncio
async def test_weather_forecast_falls_back_to_kv() -> None:
    data = _make_forecast_response(days=2)
    with (
        patch("agent.mcp.weather._kv_get", new=AsyncMock(side_effect=lambda k: "51.5" if k == "user_lat" else "-0.1")),
        patch("httpx.AsyncClient", return_value=_mock_httpx(data)) as mock_client_cls,
    ):
        await weather.weather_forecast(days=2)

    call_kwargs = mock_client_cls.return_value.__aenter__.return_value.get.call_args
    params = call_kwargs[1]["params"]
    assert params["latitude"] == 51.5
    assert params["longitude"] == -0.1
