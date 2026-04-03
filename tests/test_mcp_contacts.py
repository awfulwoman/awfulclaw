"""Unit tests for agent/mcp/contacts.py — uses mocked CNContactStore."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import agent.mcp.contacts as ct


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_phone(value: str) -> MagicMock:
    phone_value = MagicMock()
    phone_value.stringValue.return_value = value
    labeled = MagicMock()
    labeled.value.return_value = phone_value
    return labeled


def _make_email(value: str) -> MagicMock:
    labeled = MagicMock()
    labeled.value.return_value = value
    return labeled


def _make_contact(
    id: str = "cnt-1",
    given: str = "Alice",
    family: str = "Smith",
    org: str = "",
    emails: list[str] | None = None,
    phones: list[str] | None = None,
) -> MagicMock:
    c = MagicMock()
    c.identifier.return_value = id
    c.givenName.return_value = given
    c.familyName.return_value = family
    c.organizationName.return_value = org
    c.emailAddresses.return_value = [_make_email(e) for e in (emails or [])]
    c.phoneNumbers.return_value = [_make_phone(p) for p in (phones or [])]
    return c


def _make_store(
    contacts: list[Any] | None = None,
    get_contact: Any = None,
) -> MagicMock:
    store = MagicMock()
    store.unifiedContactsMatchingPredicate_keysToFetch_error_.return_value = contacts or []
    store.unifiedContactWithIdentifier_keysToFetch_error_.return_value = get_contact
    return store


def _patch_store(monkeypatch: pytest.MonkeyPatch, store: MagicMock) -> None:
    monkeypatch.setattr(ct, "_get_store", lambda: store)


def _patch_cn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _CN and _fetch_keys so no Contacts framework is needed."""
    mock_cn = MagicMock()
    mock_cn.CNContact.predicateForContactsMatchingName_.return_value = MagicMock()
    monkeypatch.setattr(ct, "_CN", mock_cn)
    monkeypatch.setattr(ct, "_fetch_keys", lambda: [])


# ---------------------------------------------------------------------------
# contacts_search
# ---------------------------------------------------------------------------


async def test_contacts_search_returns_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    alice = _make_contact(id="cnt-1", given="Alice", family="Smith", emails=["alice@example.com"], phones=["+1-555-0100"])
    store = _make_store(contacts=[alice])
    _patch_store(monkeypatch, store)
    _patch_cn(monkeypatch)

    results = await ct.contacts_search("Alice")

    assert len(results) == 1
    assert results[0]["id"] == "cnt-1"
    assert results[0]["name"] == "Alice Smith"
    assert results[0]["emails"] == ["alice@example.com"]
    assert results[0]["phones"] == ["+1-555-0100"]


async def test_contacts_search_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store(contacts=[])
    _patch_store(monkeypatch, store)
    _patch_cn(monkeypatch)

    results = await ct.contacts_search("nobody")

    assert results == []


async def test_contacts_search_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    alice = _make_contact(id="cnt-1", given="Alice", family="Smith")
    bob = _make_contact(id="cnt-2", given="Bob", family="Smith")
    store = _make_store(contacts=[alice, bob])
    _patch_store(monkeypatch, store)
    _patch_cn(monkeypatch)

    results = await ct.contacts_search("Smith")

    assert len(results) == 2
    ids = {r["id"] for r in results}
    assert ids == {"cnt-1", "cnt-2"}


async def test_contacts_search_org_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contact with no given/family name uses organization as name."""
    c = _make_contact(id="cnt-3", given="", family="", org="Acme Corp")
    store = _make_store(contacts=[c])
    _patch_store(monkeypatch, store)
    _patch_cn(monkeypatch)

    results = await ct.contacts_search("Acme")

    assert results[0]["name"] == "Acme Corp"
    assert results[0]["organization"] == "Acme Corp"


# ---------------------------------------------------------------------------
# contacts_get
# ---------------------------------------------------------------------------


async def test_contacts_get_found(monkeypatch: pytest.MonkeyPatch) -> None:
    alice = _make_contact(id="cnt-1", given="Alice", family="Smith", emails=["alice@example.com"])
    store = _make_store(get_contact=alice)
    _patch_store(monkeypatch, store)
    _patch_cn(monkeypatch)

    result = await ct.contacts_get("cnt-1")

    assert result is not None
    assert result["id"] == "cnt-1"
    assert result["given_name"] == "Alice"
    assert result["family_name"] == "Smith"
    assert result["emails"] == ["alice@example.com"]


async def test_contacts_get_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store(get_contact=None)
    _patch_store(monkeypatch, store)
    _patch_cn(monkeypatch)

    result = await ct.contacts_get("nonexistent-id")

    assert result is None
