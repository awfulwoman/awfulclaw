# Live User-Interaction Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write `tests/test_live_agent.py` — a pytest suite that hits a running awfulclaw agent at `localhost:8080` and verifies it can complete real user-interaction tasks without producing access/permission errors.

**Architecture:** All tests POST to `/chat` via httpx. A `LiveAgent` helper class wraps the HTTP client. Action messages append `ACTION_SUFFIX` requesting `STATUS: OK` / `STATUS: ERROR` tokens. macOS-specific tests skip automatically when env vars are absent.

**Tech Stack:** pytest, pytest-asyncio, httpx, pytest-timeout

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tests/test_live_agent.py` | Create | All live tests, LiveAgent class, helpers, skip markers |
| `pyproject.toml` | Modify | Add pytest-timeout dependency; exclude live tests from normal run |

---

### Task 0: Add pytest-timeout dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest-timeout to dev dependencies**

In `pyproject.toml`, find the line `"pytest-asyncio>=0.23",` and add after it:

```toml
"pytest-timeout>=2.3",
```

- [ ] **Step 2: Sync the environment**

```bash
uv sync
```

Expected: `pytest-timeout` appears in output as installed

- [ ] **Step 3: Verify the plugin loads**

```bash
uv run pytest --co -q 2>&1 | head -5
```

Expected: no error about missing timeout plugin

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pytest-timeout dependency"
```

---

### Task 1: Scaffold the file — LiveAgent class and shared helpers

**Files:**
- Create: `tests/test_live_agent.py`

- [ ] **Step 1: Create the file with imports, LiveAgent class, and helpers**

```python
"""Live integration tests for awfulclaw.

Requires the agent to be running at localhost:8080 before executing.
Run with: uv run pytest tests/test_live_agent.py -v

Apple integrations (calendar, reminders, contacts, email) are skipped unless
the corresponding env var is set:
  AWFULCLAW_TEST_EVENTKIT=1   — calendar and reminders
  AWFULCLAW_TEST_CONTACTS=1   — contacts
  AWFULCLAW_TEST_IMAP=1       — email
"""
from __future__ import annotations

import asyncio
import os
import re

import httpx
import pytest

# ---------------------------------------------------------------------------
# Suffix appended to action messages so the agent signals success/failure
# ---------------------------------------------------------------------------

ACTION_SUFFIX = (
    " If you succeeded, end your reply with STATUS: OK."
    " If anything went wrong, end with STATUS: ERROR."
)

# ---------------------------------------------------------------------------
# Phrases that indicate the agent hit a permissions / access wall
# ---------------------------------------------------------------------------

_ERROR_PHRASES = [
    "need permission",
    "cannot access",
    "don't have access",
    "unable to access",
    "access denied",
    "not authorized",
    "can't access",
    "no permission",
]

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

require_eventkit = pytest.mark.skipif(
    not os.getenv("AWFULCLAW_TEST_EVENTKIT"),
    reason="Set AWFULCLAW_TEST_EVENTKIT=1 to run Apple EventKit tests (calendar/reminders)",
)

require_contacts = pytest.mark.skipif(
    not os.getenv("AWFULCLAW_TEST_CONTACTS"),
    reason="Set AWFULCLAW_TEST_CONTACTS=1 to run Apple Contacts tests",
)

require_imap = pytest.mark.skipif(
    not os.getenv("AWFULCLAW_TEST_IMAP"),
    reason="Set AWFULCLAW_TEST_IMAP=1 to run IMAP email tests",
)

# ---------------------------------------------------------------------------
# LiveAgent HTTP client
# ---------------------------------------------------------------------------


class LiveAgent:
    """Thin wrapper around httpx that talks to the running agent."""

    def __init__(self, base_url: str = "http://localhost:8080") -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=180.0)

    async def chat(self, message: str) -> str:
        """Send a message and return the agent's reply text."""
        resp = await self._client.post("/chat", json={"message": message})
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "reply" in data, f"No 'reply' key in response: {data}"
        return data["reply"]

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_no_errors(reply: str) -> None:
    """Fail if the reply contains any access/permission error phrase."""
    lower = reply.lower()
    for phrase in _ERROR_PHRASES:
        assert phrase not in lower, f"Agent error phrase {phrase!r} detected in: {reply!r}"


def assert_ok(reply: str) -> None:
    """Fail if the reply does not contain STATUS: OK."""
    assert "STATUS: OK" in reply, f"Expected STATUS: OK in reply: {reply!r}"


def assert_contains_digit(reply: str) -> None:
    """Fail if the reply contains no digit (used for count responses)."""
    assert re.search(r"\d", reply), f"Expected a number in reply: {reply!r}"
```

- [ ] **Step 2: Verify the file collects with no errors**

```bash
uv run pytest tests/test_live_agent.py --collect-only -q
```

Expected output: `no tests ran` (no tests defined yet — that's correct at this stage)

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_agent.py
git commit -m "feat: scaffold live test file with LiveAgent class and helpers"
```

---

### Task 2: Basic connectivity tests

**Files:**
- Modify: `tests/test_live_agent.py`

- [ ] **Step 1: Append the basic tests**

Add to the end of `tests/test_live_agent.py`:

```python
# ===========================================================================
# Basic connectivity
# ===========================================================================


@pytest.mark.asyncio
async def test_basic_ping() -> None:
    """Agent responds with 'pong' when asked."""
    agent = LiveAgent()
    try:
        reply = await agent.chat("respond with only the word pong")
        assert "pong" in reply.lower(), f"Expected 'pong' in reply: {reply!r}"
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_web_fact() -> None:
    """Agent can answer a factual question that requires external knowledge."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            "in one sentence, who was the first person to walk on the moon?"
        )
        assert reply.strip(), "Reply was empty"
        assert_no_errors(reply)
    finally:
        await agent.aclose()
```

- [ ] **Step 2: Verify tests collect**

```bash
uv run pytest tests/test_live_agent.py --collect-only -q
```

Expected: 2 tests listed (`test_basic_ping`, `test_web_fact`)

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_agent.py
git commit -m "feat: add basic connectivity live tests (ping, web fact)"
```

---

### Task 3: Memory tests — user facts and general facts

**Files:**
- Modify: `tests/test_live_agent.py`

- [ ] **Step 1: Append the memory tests**

Add to the end of `tests/test_live_agent.py`:

```python
# ===========================================================================
# Memory — user facts
# ===========================================================================


@pytest.mark.asyncio
async def test_user_fact_write() -> None:
    """Agent stores a fact about the user."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            "remember that my favourite colour is indigo" + ACTION_SUFFIX
        )
        assert_no_errors(reply)
        assert_ok(reply)
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_user_fact_read() -> None:
    """Agent recalls the fact written by test_user_fact_write."""
    agent = LiveAgent()
    try:
        reply = await agent.chat("what is my favourite colour?")
        assert_no_errors(reply)
        assert "indigo" in reply.lower(), f"Expected 'indigo' in reply: {reply!r}"
    finally:
        await agent.aclose()


# ===========================================================================
# Memory — general facts
# ===========================================================================


@pytest.mark.asyncio
async def test_general_fact_write() -> None:
    """Agent stores an arbitrary fact."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            "remember that the capital of awfulworld is Awfulton" + ACTION_SUFFIX
        )
        assert_no_errors(reply)
        assert_ok(reply)
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_general_fact_read() -> None:
    """Agent recalls the general fact written by test_general_fact_write."""
    agent = LiveAgent()
    try:
        reply = await agent.chat("what is the capital of awfulworld?")
        assert_no_errors(reply)
        assert "awfulton" in reply.lower(), f"Expected 'awfulton' in reply: {reply!r}"
    finally:
        await agent.aclose()
```

- [ ] **Step 2: Verify tests collect**

```bash
uv run pytest tests/test_live_agent.py --collect-only -q
```

Expected: 6 tests listed

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_agent.py
git commit -m "feat: add memory live tests (user facts, general facts)"
```

---

### Task 4: Schedule tests — create, list, fire, delete

**Files:**
- Modify: `tests/test_live_agent.py`

- [ ] **Step 1: Append the schedule tests**

Add to the end of `tests/test_live_agent.py`:

```python
# ===========================================================================
# Schedules
# ===========================================================================

_SCHEDULE_NAME = "test-heartbeat"


@pytest.mark.asyncio
async def test_schedule_create() -> None:
    """Agent creates a recurring schedule."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            f"create a schedule called {_SCHEDULE_NAME} that runs every minute"
            f" and checks that 1+1=2" + ACTION_SUFFIX
        )
        assert_no_errors(reply)
        assert_ok(reply)
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_schedule_list() -> None:
    """The /schedules slash command lists the created schedule."""
    agent = LiveAgent()
    try:
        reply = await agent.chat("/schedules")
        assert _SCHEDULE_NAME in reply, (
            f"Expected {_SCHEDULE_NAME!r} in /schedules reply: {reply!r}"
        )
    finally:
        await agent.aclose()


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_schedule_fires() -> None:
    """The scheduler executes test-heartbeat within 90 seconds of creation."""
    agent = LiveAgent()
    try:
        deadline = asyncio.get_event_loop().time() + 90
        _not_run_phrases = ("never", "null", "hasn't run", "not run", "no record", "not yet")

        while asyncio.get_event_loop().time() < deadline:
            reply = await agent.chat(
                f"what is the last run time of the schedule called {_SCHEDULE_NAME}?"
            )
            lower = reply.lower()
            if not any(p in lower for p in _not_run_phrases):
                return  # last_run timestamp appeared — schedule fired
            await asyncio.sleep(10)

        pytest.fail(
            f"{_SCHEDULE_NAME!r} schedule did not fire within 90 seconds"
        )
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_schedule_delete() -> None:
    """Agent deletes the test schedule."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            f"delete the schedule called {_SCHEDULE_NAME}" + ACTION_SUFFIX
        )
        assert_no_errors(reply)
        assert_ok(reply)
    finally:
        await agent.aclose()
```

- [ ] **Step 2: Verify tests collect**

```bash
uv run pytest tests/test_live_agent.py --collect-only -q
```

Expected: 10 tests listed

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_agent.py
git commit -m "feat: add schedule live tests (create, list, fire, delete)"
```

---

### Task 5: Apple EventKit tests — reminders and calendar

**Files:**
- Modify: `tests/test_live_agent.py`

- [ ] **Step 1: Append the EventKit tests**

Add to the end of `tests/test_live_agent.py`:

```python
# ===========================================================================
# Apple EventKit — reminders and calendar
# (requires AWFULCLAW_TEST_EVENTKIT=1 and TCC permissions)
# ===========================================================================


@require_eventkit
@pytest.mark.asyncio
async def test_reminder_create() -> None:
    """Agent creates an Apple Reminder."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            "create a reminder called awfulclaw-test-reminder" + ACTION_SUFFIX
        )
        assert_no_errors(reply)
        assert_ok(reply)
    finally:
        await agent.aclose()


@require_eventkit
@pytest.mark.asyncio
async def test_calendar_event_create() -> None:
    """Agent creates an Apple Calendar event."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            "create a calendar event called awfulclaw-test-event tomorrow at noon"
            + ACTION_SUFFIX
        )
        assert_no_errors(reply)
        assert_ok(reply)
    finally:
        await agent.aclose()
```

- [ ] **Step 2: Verify tests collect**

```bash
uv run pytest tests/test_live_agent.py --collect-only -q
```

Expected: 12 tests listed (10 + 2 eventkit — they appear even when the marker would skip them at runtime)

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_agent.py
git commit -m "feat: add Apple EventKit live tests (reminder, calendar)"
```

---

### Task 6: Contacts and email tests

**Files:**
- Modify: `tests/test_live_agent.py`

- [ ] **Step 1: Append contacts and email tests**

Add to the end of `tests/test_live_agent.py`:

```python
# ===========================================================================
# Apple Contacts
# (requires AWFULCLAW_TEST_CONTACTS=1 and TCC permissions)
# ===========================================================================


@require_contacts
@pytest.mark.asyncio
async def test_contact_lookup() -> None:
    """Agent can query Apple Contacts and return a count."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            "look up my contacts and tell me how many you can see"
        )
        assert_no_errors(reply)
        assert_contains_digit(reply)
    finally:
        await agent.aclose()


# ===========================================================================
# Email via IMAP
# (requires AWFULCLAW_TEST_IMAP=1 and IMAP credentials configured)
# ===========================================================================


@require_imap
@pytest.mark.asyncio
async def test_email_read() -> None:
    """Agent can check recent emails and return an unread count."""
    agent = LiveAgent()
    try:
        reply = await agent.chat(
            "check my recent emails and tell me how many unread messages you can see"
        )
        assert_no_errors(reply)
        assert_contains_digit(reply)
    finally:
        await agent.aclose()
```

- [ ] **Step 2: Verify tests collect**

```bash
uv run pytest tests/test_live_agent.py --collect-only -q
```

Expected: 14 tests listed

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_agent.py
git commit -m "feat: add contacts and email live tests"
```

---

### Task 7: Exclude live tests from normal pytest run

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add ignore to pytest config**

In `pyproject.toml`, update the `[tool.pytest.ini_options]` section from:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

to:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "--ignore=tests/test_live_agent.py"
```

- [ ] **Step 2: Verify normal test run excludes live tests**

```bash
uv run pytest --collect-only -q 2>&1 | grep "test_live_agent"
```

Expected: no output (live tests not collected)

- [ ] **Step 3: Verify live tests still run explicitly**

```bash
uv run pytest tests/test_live_agent.py --collect-only -q
```

Expected: 14 tests listed

- [ ] **Step 4: Run existing test suite to confirm nothing broke**

```bash
uv run pytest -x -q
```

Expected: all existing tests pass

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: exclude live tests from default pytest run"
```
