"""Tests for email_triage module — written TDD, red before green."""
from __future__ import annotations

import pytest

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.email_triage import is_bulk, merge_triage_results, parse_local_model_verdict, EmailTriageJob


# ---------------------------------------------------------------------------
# Tier 1: header-based bulk detection
# ---------------------------------------------------------------------------

def test_list_unsubscribe_header_is_bulk():
    headers = {"list-unsubscribe": "<mailto:unsub@example.com>"}
    assert is_bulk(headers) is True


def test_precedence_bulk_is_bulk():
    headers = {"precedence": "bulk"}
    assert is_bulk(headers) is True


def test_precedence_list_is_bulk():
    headers = {"precedence": "list"}
    assert is_bulk(headers) is True


def test_auto_submitted_is_bulk():
    headers = {"auto-submitted": "auto-generated"}
    assert is_bulk(headers) is True


def test_personal_email_is_not_bulk():
    headers = {"from": "alice@example.com", "subject": "Lunch tomorrow?"}
    assert is_bulk(headers) is False


def test_header_keys_are_case_insensitive():
    headers = {"List-Unsubscribe": "<mailto:unsub@example.com>"}
    assert is_bulk(headers) is True


# ---------------------------------------------------------------------------
# Triage result merging
# ---------------------------------------------------------------------------

def test_merge_into_empty_existing():
    existing = {}
    new = {"newsletters": ["Sale today!"], "routine": [], "escalate": []}
    result = merge_triage_results(existing, new)
    assert result["newsletters"] == ["Sale today!"]
    assert result["routine"] == []
    assert result["escalate"] == []


def test_merge_accumulates_across_runs():
    existing = {"newsletters": ["A"], "routine": ["B"], "escalate": []}
    new = {"newsletters": ["C"], "routine": [], "escalate": ["D"]}
    result = merge_triage_results(existing, new)
    assert result["newsletters"] == ["A", "C"]
    assert result["routine"] == ["B"]
    assert result["escalate"] == ["D"]


def test_merge_does_not_mutate_existing():
    existing = {"newsletters": ["A"], "routine": [], "escalate": []}
    new = {"newsletters": ["B"], "routine": [], "escalate": []}
    merge_triage_results(existing, new)
    assert existing["newsletters"] == ["A"]


# ---------------------------------------------------------------------------
# Tier 2: local model response parsing
# ---------------------------------------------------------------------------

def test_parse_routine_verdict():
    raw = '{"verdict": "routine", "summary": "Amazon parcel delivered to locker"}'
    verdict, summary = parse_local_model_verdict(raw)
    assert verdict == "routine"
    assert summary == "Amazon parcel delivered to locker"


def test_parse_escalate_verdict():
    raw = '{"verdict": "escalate", "summary": "Invoice requires approval"}'
    verdict, summary = parse_local_model_verdict(raw)
    assert verdict == "escalate"
    assert summary == "Invoice requires approval"


def test_parse_handles_extra_text_around_json():
    raw = 'Sure! {"verdict": "routine", "summary": "Order confirmed"}'
    verdict, summary = parse_local_model_verdict(raw)
    assert verdict == "routine"


def test_parse_defaults_to_escalate_on_invalid_response():
    verdict, summary = parse_local_model_verdict("I don't understand")
    assert verdict == "escalate"
    assert isinstance(summary, str)


# ---------------------------------------------------------------------------
# EmailTriageJob fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.filter_unseen_email_uids = AsyncMock(return_value=[])
    store.mark_email_uids_seen = AsyncMock()
    store.kv_get = AsyncMock(return_value=None)
    store.kv_set = AsyncMock()
    return store


@pytest.fixture
def job(mock_store):
    return EmailTriageJob(
        store=mock_store,
        ollama_url="http://localhost:11434",
        ollama_model="qwen3:1.7b",
        imap_run=AsyncMock(return_value=[]),
        imap_read=AsyncMock(return_value=""),
    )


# ---------------------------------------------------------------------------
# EmailTriageJob behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_does_nothing_when_no_new_emails(job, mock_store):
    await job.run()
    mock_store.kv_set.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_email_goes_to_newsletters(mock_store):
    emails = [{"uid": "1", "subject": "50% off today!", "from": "deals@shop.com", "date": "Mon, 1 Jan 2024"}]
    mock_store.filter_unseen_email_uids = AsyncMock(return_value=["1"])

    job = EmailTriageJob(
        store=mock_store,
        ollama_url="http://localhost:11434",
        ollama_model="qwen3:1.7b",
        imap_run=AsyncMock(return_value=emails),
        imap_read=AsyncMock(return_value=""),
        get_headers=AsyncMock(return_value={"list-unsubscribe": "<mailto:u@shop.com>"}),
    )
    await job.run()

    saved = json.loads(mock_store.kv_set.call_args[0][1])
    assert "50% off today!" in saved["newsletters"][0]
    assert saved["escalate"] == []


@pytest.mark.asyncio
async def test_routine_email_goes_to_routine(mock_store):
    emails = [{"uid": "2", "subject": "Your parcel has been delivered", "from": "amazon@amazon.com", "date": "Mon, 1 Jan 2024"}]
    mock_store.filter_unseen_email_uids = AsyncMock(return_value=["2"])

    local_model_response = '{"verdict": "routine", "summary": "Amazon parcel delivered to locker"}'

    job = EmailTriageJob(
        store=mock_store,
        ollama_url="http://localhost:11434",
        ollama_model="qwen3:1.7b",
        imap_run=AsyncMock(return_value=emails),
        imap_read=AsyncMock(return_value="Your parcel has been delivered to locker ABC."),
        get_headers=AsyncMock(return_value={}),
        local_model_call=AsyncMock(return_value=local_model_response),
    )
    await job.run()

    saved = json.loads(mock_store.kv_set.call_args[0][1])
    assert saved["routine"] == ["Amazon parcel delivered to locker"]
    assert saved["escalate"] == []


@pytest.mark.asyncio
async def test_escalated_email_goes_to_escalate(mock_store):
    emails = [{"uid": "3", "subject": "Urgent: invoice overdue", "from": "accounts@company.com", "date": "Mon, 1 Jan 2024"}]
    mock_store.filter_unseen_email_uids = AsyncMock(return_value=["3"])

    local_model_response = '{"verdict": "escalate", "summary": "Invoice overdue notice"}'

    job = EmailTriageJob(
        store=mock_store,
        ollama_url="http://localhost:11434",
        ollama_model="qwen3:1.7b",
        imap_run=AsyncMock(return_value=emails),
        imap_read=AsyncMock(return_value="Your invoice is 30 days overdue."),
        get_headers=AsyncMock(return_value={}),
        local_model_call=AsyncMock(return_value=local_model_response),
    )
    await job.run()

    saved = json.loads(mock_store.kv_set.call_args[0][1])
    assert saved["escalate"][0]["summary"] == "Invoice overdue notice"
    assert saved["escalate"][0]["uid"] == "3"


@pytest.mark.asyncio
async def test_marks_all_processed_uids_as_seen(mock_store):
    emails = [
        {"uid": "1", "subject": "Sale", "from": "a@b.com", "date": "Mon, 1 Jan 2024"},
        {"uid": "2", "subject": "Hello", "from": "c@d.com", "date": "Mon, 1 Jan 2024"},
    ]
    mock_store.filter_unseen_email_uids = AsyncMock(return_value=["1", "2"])

    job = EmailTriageJob(
        store=mock_store,
        ollama_url="http://localhost:11434",
        ollama_model="qwen3:1.7b",
        imap_run=AsyncMock(return_value=emails),
        imap_read=AsyncMock(return_value="body text"),
        get_headers=AsyncMock(return_value={"list-unsubscribe": "yes"}),
        local_model_call=AsyncMock(return_value='{"verdict": "routine", "summary": "ok"}'),
    )
    await job.run()

    seen_uids = mock_store.mark_email_uids_seen.call_args[0][0]
    assert set(seen_uids) == {"1", "2"}


@pytest.mark.asyncio
async def test_merges_with_existing_triage_results(mock_store):
    existing = {"newsletters": ["Old newsletter"], "routine": [], "escalate": []}
    mock_store.kv_get = AsyncMock(return_value=json.dumps(existing))

    emails = [{"uid": "5", "subject": "Delivery update", "from": "ups@ups.com", "date": "Mon, 1 Jan 2024"}]
    mock_store.filter_unseen_email_uids = AsyncMock(return_value=["5"])

    job = EmailTriageJob(
        store=mock_store,
        ollama_url="http://localhost:11434",
        ollama_model="qwen3:1.7b",
        imap_run=AsyncMock(return_value=emails),
        imap_read=AsyncMock(return_value="Your package is on its way."),
        get_headers=AsyncMock(return_value={}),
        local_model_call=AsyncMock(return_value='{"verdict": "routine", "summary": "Delivery update"}'),
    )
    await job.run()

    saved = json.loads(mock_store.kv_set.call_args[0][1])
    assert "Old newsletter" in saved["newsletters"]
    assert "Delivery update" in saved["routine"]
