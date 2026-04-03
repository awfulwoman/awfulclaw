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
