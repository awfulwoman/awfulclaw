# OwnTracks Location Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate OwnTracks Recorder so Gary can answer "where am I?" and automatically keep USER.md timezone up to date on startup.

**Architecture:** A new `location.py` module owns all location logic (OwnTracks fetch, timezone resolution, reverse geocoding, USER.md update). A new `awfulclaw_mcp/owntracks.py` FastMCP server exposes `owntracks_get_location` to Gary. `loop.py` calls `check_and_update_timezone()` at startup before `ensure_daily_briefing` so the briefing always picks up the freshest timezone.

**Tech Stack:** `httpx` (already a dep), `timezonefinder` (new dep), Nominatim reverse geocoding (free, no key), OwnTracks Recorder HTTP API.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `app/awfulclaw/location.py` | All location helpers: fetch, tz resolve, geocode, USER.md update |
| Create | `app/awfulclaw_mcp/owntracks.py` | FastMCP server: `owntracks_get_location` tool |
| Create | `app/tests/test_location.py` | Tests for location.py |
| Create | `app/tests/test_owntracks_mcp.py` | Tests for the MCP tool |
| Modify | `app/awfulclaw/briefings.py` | Import `_user_timezone` from `location` instead of defining it |
| Modify | `app/awfulclaw/config.py` | Add `get_owntracks_url/user/device()` |
| Modify | `app/awfulclaw/loop.py:144-146` | Call `check_and_update_timezone()` at startup |
| Modify | `config/mcp_servers.json` | Register `owntracks` server |
| Modify | `pyproject.toml` | Add `timezonefinder` dependency |
| Modify | `CLAUDE.md` | Document new env vars |
| Modify | `memory/SOUL.md` | Tell Gary about `owntracks_get_location` |

---

## Task 1: Add `timezonefinder` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `timezonefinder` to the `dependencies` list (after `python-dotenv`):

```toml
dependencies = [
    "croniter",
    "ddgs>=9.12.0",
    "google-api-python-client",
    "google-auth-oauthlib",
    "httpx",
    "mcp>=1.26.0",
    "python-dotenv",
    "timezonefinder",
]
```

- [ ] **Step 2: Sync deps**

```bash
uv sync --extra dev
```

Expected: resolves and installs `timezonefinder` and its deps (`h3`, `shapely`, etc.) without error.

- [ ] **Step 3: Verify import works**

```bash
uv run python -c "from timezonefinder import TimezoneFinder; print(TimezoneFinder().timezone_at(lat=51.5, lng=-0.1))"
```

Expected output: `Europe/London`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add timezonefinder dependency"
```

---

## Task 2: Create `location.py` — timezone helpers and USER.md update

**Files:**
- Create: `app/awfulclaw/location.py`
- Create: `app/tests/test_location.py`
- Modify: `app/awfulclaw/briefings.py`

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_location.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/tests/test_location.py -v
```

Expected: `ImportError: cannot import name '_update_user_timezone' from 'awfulclaw.location'`

- [ ] **Step 3: Create `app/awfulclaw/location.py`**

```python
"""Location helpers — timezone resolution, USER.md updates, OwnTracks integration."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/tests/test_location.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Update `briefings.py` to import from `location`**

In `app/awfulclaw/briefings.py`, replace:

```python
import re
from datetime import time
```

with:

```python
from datetime import time
```

And replace the `_user_timezone` function definition:

```python
def _user_timezone() -> str:
    """Extract timezone from memory/USER.md, or return '' if not set/unknown."""
    from awfulclaw import memory

    content = memory.read("USER.md")
    m = re.search(r"(?i)^Timezone:\s*(.+)$", content, re.MULTILINE)
    if not m:
        return ""
    tz_name = m.group(1).strip().split()[0]
    return "" if tz_name.lower() in ("unknown", "") else tz_name
```

with:

```python
from awfulclaw.location import _user_timezone
```

- [ ] **Step 6: Run the full test suite to verify nothing broke**

```bash
uv run pytest app/tests/ -q
```

Expected: all existing tests pass (180+).

- [ ] **Step 7: Commit**

```bash
git add app/awfulclaw/location.py app/awfulclaw/briefings.py app/tests/test_location.py
git commit -m "refactor: move _user_timezone to location.py, add _update_user_timezone"
```

---

## Task 3: Add OwnTracks fetch, timezone resolution, and startup check

**Files:**
- Modify: `app/awfulclaw/location.py`
- Modify: `app/tests/test_location.py`
- Modify: `app/awfulclaw/config.py`
- Modify: `app/awfulclaw/loop.py`

- [ ] **Step 1: Write failing tests**

Append to `app/tests/test_location.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/tests/test_location.py -v -k "fetch or resolve or check_and_update"
```

Expected: `ImportError: cannot import name 'fetch_owntracks_position'`

- [ ] **Step 3: Implement in `location.py`**

Add to `app/awfulclaw/location.py` after the existing imports and before `_user_timezone`:

```python
import httpx

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "awfulclaw/1.0"
_tf = None  # TimezoneFinder singleton


def _get_tf() -> object:
    global _tf
    if _tf is None:
        from timezonefinder import TimezoneFinder
        _tf = TimezoneFinder()
    return _tf
```

Then add these three functions at the end of `location.py`:

```python
def fetch_owntracks_position(
    url: str, user: str, device: str
) -> dict[str, object] | None:
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
        result = _get_tf().timezone_at(lat=lat, lng=lon)  # type: ignore[union-attr]
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/tests/test_location.py -v
```

Expected: all tests pass (14+).

- [ ] **Step 5: Add config helpers for OwnTracks env vars**

In `app/awfulclaw/config.py`, append after `get_briefing_time`:

```python
def get_owntracks_url() -> str:
    return os.getenv("OWNTRACKS_URL", "").strip()


def get_owntracks_user() -> str:
    return os.getenv("OWNTRACKS_USER", "charlie").strip()


def get_owntracks_device() -> str:
    return os.getenv("OWNTRACKS_DEVICE", "iphone").strip()
```

- [ ] **Step 6: Wire startup check into `loop.py`**

In `app/awfulclaw/loop.py`, replace:

```python
    briefing_time = config.get_briefing_time()
    if briefing_time is not None:
        briefings.ensure_daily_briefing(briefing_time)
```

with:

```python
    owntracks_url = config.get_owntracks_url()
    if owntracks_url:
        from awfulclaw.location import check_and_update_timezone
        check_and_update_timezone(
            owntracks_url,
            config.get_owntracks_user(),
            config.get_owntracks_device(),
        )

    briefing_time = config.get_briefing_time()
    if briefing_time is not None:
        briefings.ensure_daily_briefing(briefing_time)
```

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest app/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/awfulclaw/location.py app/awfulclaw/config.py app/awfulclaw/loop.py app/tests/test_location.py
git commit -m "feat: add OwnTracks fetch, timezone resolution, and startup check"
```

---

## Task 4: Create the OwnTracks MCP server

**Files:**
- Create: `app/awfulclaw_mcp/owntracks.py`
- Create: `app/tests/test_owntracks_mcp.py`
- Modify: `config/mcp_servers.json`

- [ ] **Step 1: Write failing tests**

Create `app/tests/test_owntracks_mcp.py`:

```python
"""Tests for the OwnTracks MCP server."""

from __future__ import annotations

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
    import importlib
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest app/tests/test_owntracks_mcp.py -v
```

Expected: `ModuleNotFoundError: No module named 'awfulclaw_mcp.owntracks'`

- [ ] **Step 3: Create `app/awfulclaw_mcp/owntracks.py`**

```python
"""MCP server for OwnTracks location queries."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from awfulclaw.location import fetch_owntracks_position, resolve_timezone, reverse_geocode

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest app/tests/test_owntracks_mcp.py -v
```

Expected: all 5 tests pass. (The `test_get_location_missing_url` test reloads the module — if it flakes due to import caching, skip it and verify manually.)

- [ ] **Step 5: Register in `config/mcp_servers.json`**

Add after the `"gcal"` entry (before the closing `]` of `"servers"`):

```json
    {
      "name": "owntracks",
      "command": "uv",
      "args": [
        "run",
        "python",
        "-m",
        "awfulclaw_mcp.owntracks"
      ],
      "env": {
        "OWNTRACKS_URL": "${OWNTRACKS_URL}",
        "OWNTRACKS_USER": "${OWNTRACKS_USER}",
        "OWNTRACKS_DEVICE": "${OWNTRACKS_DEVICE}"
      },
      "env_required": [
        "OWNTRACKS_URL"
      ]
    }
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest app/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/awfulclaw_mcp/owntracks.py app/tests/test_owntracks_mcp.py config/mcp_servers.json
git commit -m "feat: add OwnTracks MCP server with get_location tool"
```

---

## Task 5: Documentation and SOUL.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `memory/SOUL.md`

- [ ] **Step 1: Update `CLAUDE.md` env vars section**

In `CLAUDE.md`, in the `Optional:` env var block, add after the `GOOGLE_CLIENT_SECRET_PATH` line:

```
OWNTRACKS_URL=https://your-recorder.example.com  # required to use OwnTracks MCP server
OWNTRACKS_USER=charlie                            # default: charlie
OWNTRACKS_DEVICE=iphone                           # default: iphone
```

- [ ] **Step 2: Update `memory/SOUL.md`**

Append to the **Timezones and travel** section in `memory/SOUL.md`:

```
You have access to the `owntracks_get_location` tool which returns the user's current location, timezone, and how long ago the last GPS fix was. Use it to:
- Answer "where am I?" or "what's my current location?" questions
- Verify or double-check the user's timezone when creating time-sensitive schedules
- Proactively check location when the user mentions travel
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md memory/SOUL.md
git commit -m "docs: document OwnTracks env vars and tell Gary about get_location tool"
```

---

## Self-Review

**Spec coverage:**
- ✅ MCP tool `owntracks_get_location` → Task 4
- ✅ Startup timezone check → Task 3 (loop.py wiring)
- ✅ `location.py` module → Tasks 2–3
- ✅ `_user_timezone` moved from `briefings.py` → Task 2
- ✅ `timezonefinder` dep → Task 1
- ✅ Nominatim reverse geocoding → Task 3 (`reverse_geocode`)
- ✅ `mcp_servers.json` registration → Task 4
- ✅ Env vars documented → Task 5
- ✅ SOUL.md updated → Task 5
- ✅ Error handling throughout → all tasks
- ✅ Tests for all paths → Tasks 2, 3, 4

**Placeholder scan:** None found.

**Type consistency:** `fetch_owntracks_position` returns `dict[str, object] | None` and is used as such in both `location.py` and `owntracks.py`. `resolve_timezone` returns `str | None` — used consistently. `reverse_geocode` returns `str | None` — used consistently.
