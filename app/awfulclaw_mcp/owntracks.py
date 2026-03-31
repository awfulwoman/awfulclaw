"""MCP server for OwnTracks location queries."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from awfulclaw.location import fetch_owntracks_position, resolve_timezone, reverse_geocode
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("owntracks")

_URL = os.getenv("OWNTRACKS_URL", "").strip()
_USER = os.getenv("OWNTRACKS_USER", "charlie").strip()
_DEVICE = os.getenv("OWNTRACKS_DEVICE", "iphone").strip()


@mcp.tool()
def owntracks_get_location() -> str:
    """Get the user's current location from OwnTracks, including city, country, and timezone."""
    if not _URL:
        return "[owntracks error: OWNTRACKS_URL not configured]"

    position = fetch_owntracks_position(_URL, _USER, _DEVICE)
    if position is None:
        return "[owntracks error: could not fetch position from recorder]"

    lat = position.get("lat")
    lon = position.get("lon")
    tst = position.get("tst")

    if lat is None or lon is None:
        return "[owntracks error: response missing lat/lon]"

    lat_f, lon_f = float(lat), float(lon)

    tz = resolve_timezone(lat_f, lon_f)
    city = reverse_geocode(lat_f, lon_f)

    parts: list[str] = []
    if city:
        parts.append(city)
    if tz:
        parts.append(f"({tz})")
    if not parts:
        parts.append(f"{lat_f:.4f}, {lon_f:.4f}")

    if tst:
        try:
            dt = datetime.fromtimestamp(int(tst), tz=timezone.utc)
            age = int((datetime.now(timezone.utc) - dt).total_seconds())
            if age < 60:
                age_str = f"{age}s ago"
            elif age < 3600:
                age_str = f"{age // 60}m ago"
            else:
                age_str = f"{age // 3600}h ago"
            parts.append(f"— last fix {age_str}")
        except (ValueError, OSError):
            pass

    return " ".join(parts)


if __name__ == "__main__":
    mcp.run()
