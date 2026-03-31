"""Location helpers — timezone resolution, USER.md updates, OwnTracks integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "awfulclaw/1.0"
_tf = None  # TimezoneFinder singleton


def _get_tf() -> Any:
    global _tf
    if _tf is None:
        from timezonefinder import TimezoneFinder

        _tf = TimezoneFinder()
    return _tf


def _user_timezone() -> str:
    """Extract timezone from memory/USER.md, or return '' if not set/unknown."""
    from awfulclaw import memory

    content = memory.read("USER.md")
    m = re.search(r"(?i)^Timezone:\s*(.+)$", content, re.MULTILINE)
    if not m:
        return ""
    tz_name = m.group(1).strip().split()[0]
    return "" if tz_name.lower() in ("unknown", "") else tz_name


def _update_user_timezone(new_tz: str) -> None:
    """Update the Timezone: line in memory/USER.md in-place."""
    from awfulclaw import memory

    content = memory.read("USER.md")
    if not content:
        return
    if re.search(r"(?im)^Timezone:", content):
        updated = re.sub(
            r"(?im)^(Timezone:\s*)(.+)$",
            lambda m: m.group(1) + new_tz,
            content,
        )
    else:
        updated = content.rstrip() + f"\nTimezone: {new_tz}\n"
    if updated != content:
        memory.write("USER.md", updated)


def fetch_owntracks_position(
    url: str, user: str, device: str
) -> dict[str, Any] | None:
    """Fetch last position from OwnTracks Recorder. Returns None on error or empty response."""
    try:
        resp = httpx.get(
            f"{url.rstrip('/')}/api/0/last",
            params={"user": user, "device": device},
            timeout=10,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return dict(data[0])
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            items = data["data"]
            if items:
                return dict(items[0])
        return None
    except Exception as exc:
        logger.warning("OwnTracks fetch failed: %s", exc)
        return None


def resolve_timezone(lat: float, lon: float) -> str | None:
    """Return IANA timezone string for coordinates, or None on failure."""
    try:
        result = _get_tf().timezone_at(lat=lat, lng=lon)
        return str(result) if result else None
    except Exception as exc:
        logger.warning("Timezone resolution failed: %s", exc)
        return None


def reverse_geocode(lat: float, lon: float) -> str | None:
    """Return human-readable city/country string via Nominatim, or None on failure."""
    try:
        resp = httpx.get(
            _NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "json"},
            timeout=10,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        address = data.get("address", {})
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("hamlet", "")
        )
        country = address.get("country", "")
        parts = [p for p in (city, country) if p]
        return ", ".join(parts) if parts else None
    except Exception as exc:
        logger.warning("Nominatim reverse geocode failed: %s", exc)
        return None


def check_and_update_timezone(
    url: str, user: str = "charlie", device: str = "iphone"
) -> None:
    """Fetch current location from OwnTracks and update USER.md timezone if changed."""
    position = fetch_owntracks_position(url, user, device)
    if position is None:
        return
    lat = position.get("lat")
    lon = position.get("lon")
    if lat is None or lon is None:
        logger.warning("OwnTracks response missing lat/lon")
        return
    tz = resolve_timezone(float(lat), float(lon))
    if tz is None:
        return
    current = _user_timezone()
    if tz != current:
        logger.info("Timezone changed %r → %r, updating USER.md", current, tz)
        _update_user_timezone(tz)
