# OwnTracks Location Integration — Design

**Date:** 2026-03-31
**Status:** Approved

## Summary

Integrate the OwnTracks Recorder HTTP API so Gary can (a) answer "where am I?" and (b) automatically keep USER.md timezone up to date whenever the user's location changes, without manual intervention.

## Architecture

Four new or modified pieces, all following existing project patterns:

| Component | Purpose |
|---|---|
| `app/awfulclaw_mcp/owntracks.py` | FastMCP server exposing `owntracks_get_location` tool |
| `app/awfulclaw/location.py` | Shared location helpers + startup timezone check |
| `config/mcp_servers.json` | Register the new MCP server |
| `pyproject.toml` | Add `timezonefinder` dependency |

`_user_timezone()` is moved from `briefings.py` into `location.py`; `briefings.py` imports from there. No behaviour change.

## Components

### `app/awfulclaw_mcp/owntracks.py`

FastMCP server with a single tool: `owntracks_get_location`.

1. `GET {OWNTRACKS_URL}/api/0/last?user={OWNTRACKS_USER}&device={OWNTRACKS_DEVICE}`
2. Extract `lat`, `lon`, `tst` from response
3. `timezonefinder.timezone_at(lat=lat, lng=lon)` → IANA timezone string
4. `GET https://nominatim.openstreetmap.org/reverse?lat=...&lon=...&format=json` → city/country
5. Return human-readable summary: `"London, United Kingdom (Europe/London) — last fix 3 minutes ago"`

Errors are non-fatal: Nominatim failure omits the city name; OwnTracks failure returns a descriptive error string.

### `app/awfulclaw/location.py`

Two public functions:

**`_user_timezone()`** (moved from `briefings.py`):
Reads `Timezone:` from `memory/USER.md`, returns IANA string or `""`.

**`check_and_update_timezone()`**:
Called at startup from `loop.py`. Fetches location from OwnTracks, resolves timezone via `timezonefinder`, compares with USER.md. If different, updates the `Timezone:` line in-place and logs the change. If OwnTracks is unreachable, logs a warning and returns without touching USER.md.

### Configuration

Env vars (added to `.env` and `config/mcp_servers.json`):

| Var | Required | Default |
|---|---|---|
| `OWNTRACKS_URL` | Yes | — |
| `OWNTRACKS_USER` | No | `charlie` |
| `OWNTRACKS_DEVICE` | No | `iphone` |

`OWNTRACKS_URL` is in `env_required` so the MCP server is skipped if unset (same pattern as `imap`).

## Data Flow

```
Startup
  └── loop.py calls check_and_update_timezone()
        ├── GET /api/0/last?user=charlie&device=iphone
        ├── timezonefinder → IANA tz
        ├── compare with USER.md
        └── update USER.md if changed
              └── ensure_daily_briefing() picks up new tz (already implemented)

On-demand (Gary)
  └── owntracks_get_location MCP tool called
        ├── GET /api/0/last
        ├── timezonefinder → IANA tz
        ├── Nominatim reverse geocode → city/country
        └── return summary string to Gary
```

## Error Handling

| Failure | Behaviour |
|---|---|
| OwnTracks unreachable (startup) | Log warning, continue startup, USER.md unchanged |
| OwnTracks unreachable (MCP tool) | Return error string to Gary |
| Nominatim unreachable | Return timezone + lat/lon only, omit city |
| No fix in recorder response | Return descriptive error |
| `timezonefinder` can't resolve | Return lat/lon, omit timezone |

## Testing

**`app/tests/test_owntracks_mcp.py`**
- Happy path: mocked HTTP → correct timezone and location string
- OwnTracks unreachable → error string returned, no exception
- Nominatim unreachable → timezone returned, city omitted
- Empty/malformed recorder response → clear error message

**`app/tests/test_location.py`**
- Timezone changed → USER.md `Timezone:` line updated, rest of file unchanged
- Timezone unchanged → USER.md not written
- OwnTracks unreachable → USER.md untouched, no crash

## Dependencies

- `timezonefinder` — IANA timezone from lat/lon, no network call
- Nominatim — reverse geocoding via httpx (already a dependency), no API key required; `User-Agent: awfulclaw` header per OSM usage policy

## SOUL.md

Add a note that Gary can call `owntracks_get_location` to answer location questions and to verify current timezone when needed.
