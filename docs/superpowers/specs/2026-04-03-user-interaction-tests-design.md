# Live User-Interaction Test Suite Design

**Date:** 2026-04-03
**Status:** Approved

## Purpose

A pytest suite that validates end-to-end human conversation with the running awfulclaw agent. Tests send real HTTP requests to `localhost:8080`, check that responses are non-empty and free of access/permission error phrases, and optionally verify that data was actually stored or actions actually executed.

The goal is to catch agent failures such as:
- "I need write permission to do that"
- "I cannot access this kind of data"

Not to validate LLM reasoning quality.

## Constraints

- Agent must already be running before tests are executed (not spun up per test)
- Tests are excluded from normal `uv run pytest` runs via `--ignore` in pytest config
- Non-deterministic LLM output means assertions use substring presence/absence, not exact matching
- macOS-specific integrations (calendar, reminders, contacts, email) skip automatically when env vars are absent

## Structure

```
tests/
  test_live_agent.py   ← all live tests (new)
```

No changes to `conftest.py` or any other test file.

## `LiveAgent` Class

Plain Python class (not a pytest fixture) used inside async test functions:

```python
class LiveAgent:
    def __init__(self, base_url="http://localhost:8080"):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=180.0)

    async def chat(self, message: str) -> str:
        resp = await self.client.post("/chat", json={"message": message})
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
        return resp.json()["reply"]

    async def close(self):
        await self.client.aclose()
```

Timeout is 180s to accommodate claude CLI tool calls (typically 60-90s).

## Status Token Convention

Action messages (write, create, delete) append the instruction:

> "If you succeeded, end your reply with STATUS: OK. If anything went wrong, end with STATUS: ERROR."

This makes success/failure assertions deterministic regardless of LLM phrasing variation. Retrieval messages do not use this convention — they assert on expected values in the reply instead.

```python
ACTION_SUFFIX = (
    " If you succeeded, end your reply with STATUS: OK."
    " If anything went wrong, end with STATUS: ERROR."
)

def assert_ok(reply: str) -> None:
    assert "STATUS: OK" in reply, f"Expected STATUS: OK in reply: {reply!r}"

def assert_not_error_status(reply: str) -> None:
    assert "STATUS: ERROR" not in reply, f"Agent reported STATUS: ERROR: {reply!r}"
```

## Error Phrase Detection

Used as a secondary check on all replies (action and retrieval) to catch cases where the agent fails without using the status token:

```python
ERROR_PHRASES = [
    "need permission",
    "cannot access",
    "don't have access",
    "unable to access",
    "access denied",
    "not authorized",
    "can't access",
    "no permission",
]

def assert_no_errors(reply: str) -> None:
    lower = reply.lower()
    for phrase in ERROR_PHRASES:
        assert phrase not in lower, f"Agent error detected: {reply!r}"
```

## Skip Markers

| Marker | Env var | Reason shown |
|---|---|---|
| `require_eventkit` | `AWFULCLAW_TEST_EVENTKIT=1` | Apple EventKit (calendar/reminders) not enabled |
| `require_contacts` | `AWFULCLAW_TEST_CONTACTS=1` | Apple Contacts TCC not enabled |
| `require_imap` | `AWFULCLAW_TEST_IMAP=1` | IMAP credentials not configured |

## Test Scenarios

Tests run in file order. Write tests precede their corresponding read tests.

| Test | Message | Assertions |
|---|---|---|
| `test_basic_ping` | "respond with only the word pong" | contains "pong" |
| `test_web_fact` | "in one sentence, who was the first person to walk on the moon?" | no errors, non-empty |
| `test_user_fact_write` | "remember that my favourite colour is indigo" + ACTION_SUFFIX | STATUS: OK, no errors |
| `test_user_fact_read` | "what is my favourite colour?" | no errors, contains "indigo" |
| `test_general_fact_write` | "remember that the capital of awfulworld is Awfulton" + ACTION_SUFFIX | STATUS: OK, no errors |
| `test_general_fact_read` | "what is the capital of awfulworld?" | no errors, contains "awfulton" |
| `test_schedule_create` | "create a schedule called test-heartbeat that runs every minute and checks that 1+1=2" + ACTION_SUFFIX | STATUS: OK, no errors |
| `test_schedule_list` | "/schedules" | contains "test-heartbeat" |
| `test_schedule_fires` | (poll every 10s, timeout 90s) | last_run visible via MCP |
| `test_schedule_delete` | "delete the schedule called test-heartbeat" + ACTION_SUFFIX | STATUS: OK, no errors |
| `test_reminder_create` *(eventkit)* | "create a reminder called awfulclaw-test-reminder" + ACTION_SUFFIX | STATUS: OK, no errors |
| `test_calendar_event` *(eventkit)* | "create a calendar event called awfulclaw-test-event tomorrow at noon" + ACTION_SUFFIX | STATUS: OK, no errors |
| `test_contact_lookup` *(contacts)* | "look up my contacts and tell me how many you can see" | no errors, contains a digit |
| `test_email_read` *(imap)* | "check my recent emails and tell me how many unread messages you can see" | no errors, contains a digit |

### Schedule Fire Check

After `test_schedule_create`, `test_schedule_fires` polls every 10s for up to 90s by asking: `"what is the last run time of the schedule called test-heartbeat?"` and checking the reply does not contain "never" or "null" or "hasn't run". The `schedule_list` MCP tool returns `last_run`, so the agent will report it once the scheduler fires. Decorated with `@pytest.mark.timeout(120)`.

## Running the Suite

```bash
# Basic (no Apple integrations)
uv run pytest tests/test_live_agent.py -v

# With Apple integrations
AWFULCLAW_TEST_EVENTKIT=1 AWFULCLAW_TEST_CONTACTS=1 AWFULCLAW_TEST_IMAP=1 \
  uv run pytest tests/test_live_agent.py -v
```

## Exclusion from Normal CI

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
addopts = "--ignore=tests/test_live_agent.py"
```

## Cleanup Notes

- Fact write tests leave data in the DB (acceptable for dev machine)
- `test_schedule_delete` cleans up the test schedule
- Reminder and calendar event tests do not clean up (manual cleanup acceptable for now)
