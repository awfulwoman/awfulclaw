"""owntracks MCP server — location and timezone tracking.

Exposes:
  location_get()             — query the OwnTracks recorder for current position
  owntracks_update(payload)  — process an OwnTracks HTTP JSON payload,
                               write lat/lon and derived timezone to store.kv

Configure DB_PATH and OWNTRACKS_URL env vars.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("owntracks")


def _get_db_path() -> Path:
    return Path(os.environ.get("DB_PATH", "agent.db"))


def _get_recorder_url() -> str:
    return os.environ.get("OWNTRACKS_URL", "").rstrip("/")


@mcp.tool()
async def location_get() -> dict:
    """Return the current location from the OwnTracks recorder.

    Queries /api/0/last and returns the most recent position for all devices.
    Each entry includes lat, lon, timestamp (isotst), battery, velocity, and
    derived timezone (if available).
    """
    url = _get_recorder_url()
    if not url:
        return {"error": "OWNTRACKS_URL not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{url}/api/0/last")
            resp.raise_for_status()
            entries: list[dict] = resp.json()
    except Exception as exc:
        return {"error": str(exc)}

    results = []
    for entry in entries:
        lat = entry.get("lat")
        lon = entry.get("lon")
        tz = _timezone_from_coords(lat, lon) if lat is not None and lon is not None else None
        results.append({
            "device": f"{entry.get('username')}/{entry.get('device')}",
            "lat": lat,
            "lon": lon,
            "timestamp": entry.get("isotst"),
            "timezone": tz,
            "battery": entry.get("batt"),
            "velocity": entry.get("vel"),
            "accuracy": entry.get("acc"),
        })

    return {"locations": results}


async def _kv_set(key: str, value: str) -> None:
    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


def _timezone_from_coords(lat: float, lon: float) -> Optional[str]:
    try:
        from timezonefinder import TimezoneFinder  # type: ignore[import-untyped]

        tf = TimezoneFinder()
        return tf.timezone_at(lat=lat, lng=lon)
    except ImportError:
        return None


@mcp.tool()
async def owntracks_update(payload: str) -> str:
    """Process an OwnTracks HTTP JSON payload and update location in the kv store.

    payload: JSON string from OwnTracks (must have _type='location', lat, lon fields)

    Writes user_lat, user_lon, and user_timezone (if derivable) to store.kv.
    """
    try:
        data: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON — {exc}"

    if not isinstance(data, dict):
        return "Error: payload must be a JSON object"

    if data.get("_type") != "location":
        return f"Ignored: _type is {data.get('_type')!r}, expected 'location'"

    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        return "Error: payload missing lat or lon"

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return "Error: lat/lon must be numeric"

    await _kv_set("user_lat", str(lat))
    await _kv_set("user_lon", str(lon))

    tz = _timezone_from_coords(lat, lon)
    if tz:
        await _kv_set("user_timezone", tz)
        return f"Location updated: lat={lat}, lon={lon}, timezone={tz}"

    return f"Location updated: lat={lat}, lon={lon} (timezone not derived)"


if __name__ == "__main__":
    mcp.run()
