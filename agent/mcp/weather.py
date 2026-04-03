"""weather MCP server — current conditions and forecasts via Open-Meteo.

Exposes:
  weather_current(lat?, lon?)           — current weather conditions
  weather_forecast(lat?, lon?, days?)   — multi-day forecast

Uses Open-Meteo API (no API key required).
Defaults lat/lon from store.kv keys: user_lat, user_lon.
Configure DB_PATH env var to point at the SQLite database.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import aiosqlite
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes → human description
_WMO_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "icy fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "moderate showers",
    82: "heavy showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with light hail",
    99: "thunderstorm with heavy hail",
}


def _get_db_path() -> Path:
    raw = os.environ.get("DB_PATH", "agent.db")
    return Path(raw)


async def _kv_get(key: str) -> Optional[str]:
    db_path = _get_db_path()
    if not db_path.exists():
        return None
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def _resolve_coords(lat: Optional[float], lon: Optional[float]) -> tuple[float, float]:
    """Return (lat, lon), falling back to kv store if not provided."""
    if lat is None:
        raw = await _kv_get("user_lat")
        lat = float(raw) if raw else 0.0
    if lon is None:
        raw = await _kv_get("user_lon")
        lon = float(raw) if raw else 0.0
    return lat, lon


def _wmo_description(code: int) -> str:
    return _WMO_CODES.get(code, f"weather code {code}")


@mcp.tool()
async def weather_current(lat: Optional[float] = None, lon: Optional[float] = None) -> str:
    """Return current weather conditions as a natural language summary.

    lat/lon default to the last known location stored in the kv store
    (user_lat, user_lon). Pass explicit values to override.
    """
    lat, lon = await _resolve_coords(lat, lon)
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,precipitation,weathercode,wind_speed_10m,relative_humidity_2m",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    cur = data.get("current", {})
    units = data.get("current_units", {})
    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    precip = cur.get("precipitation")
    code = cur.get("weathercode", 0)
    wind = cur.get("wind_speed_10m")
    humidity = cur.get("relative_humidity_2m")
    temp_unit = units.get("temperature_2m", "°C")
    wind_unit = units.get("wind_speed_10m", "km/h")
    precip_unit = units.get("precipitation", "mm")

    desc = _wmo_description(int(code))
    parts = [f"Currently {desc}: {temp}{temp_unit} (feels like {feels}{temp_unit})"]
    if humidity is not None:
        parts.append(f"humidity {humidity}%")
    if wind is not None:
        parts.append(f"wind {wind} {wind_unit}")
    if precip is not None and float(precip) > 0:
        parts.append(f"precipitation {precip} {precip_unit}")
    return ", ".join(parts) + "."


@mcp.tool()
async def weather_forecast(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    days: int = 3,
) -> str:
    """Return a multi-day weather forecast as a natural language summary.

    lat/lon default to the last known location stored in the kv store.
    days: number of forecast days (1–7, default 3).
    """
    days = max(1, min(7, days))
    lat, lon = await _resolve_coords(lat, lon)
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "timezone": "auto",
        "forecast_days": days,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    daily = data.get("daily", {})
    units = data.get("daily_units", {})
    dates = daily.get("time", [])
    codes = daily.get("weathercode", [])
    maxes = daily.get("temperature_2m_max", [])
    mins = daily.get("temperature_2m_min", [])
    precips = daily.get("precipitation_sum", [])
    winds = daily.get("wind_speed_10m_max", [])
    temp_unit = units.get("temperature_2m_max", "°C")
    precip_unit = units.get("precipitation_sum", "mm")
    wind_unit = units.get("wind_speed_10m_max", "km/h")

    lines: list[str] = []
    for i, date in enumerate(dates):
        desc = _wmo_description(int(codes[i])) if i < len(codes) else "unknown"
        hi = maxes[i] if i < len(maxes) else "?"
        lo = mins[i] if i < len(mins) else "?"
        line = f"{date}: {desc}, {lo}–{hi}{temp_unit}"
        if i < len(precips) and precips[i] and float(precips[i]) > 0:
            line += f", {precips[i]}{precip_unit} rain"
        if i < len(winds) and winds[i]:
            line += f", wind up to {winds[i]} {wind_unit}"
        lines.append(line)

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
