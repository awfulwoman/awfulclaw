"""contacts MCP server — read-only contact search via macOS Contacts.

Exposes:
  contacts_search(query)   — search contacts by name, email, or phone
  contacts_get(id)         — fetch a single contact by identifier

Requires macOS with pyobjc-framework-Contacts installed.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("contacts")

try:
    import Contacts as _CN  # type: ignore[import-not-found]

    _HAS_CONTACTS = True
except ImportError:
    _CN = None  # type: ignore[assignment]
    _HAS_CONTACTS = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FETCH_KEYS: list[Any] = []  # populated lazily after import check


def _fetch_keys() -> list[Any]:
    """Return the list of CNKeyDescriptor keys to fetch."""
    return [
        _CN.CNContactGivenNameKey,  # type: ignore[union-attr]
        _CN.CNContactFamilyNameKey,  # type: ignore[union-attr]
        _CN.CNContactEmailAddressesKey,  # type: ignore[union-attr]
        _CN.CNContactPhoneNumbersKey,  # type: ignore[union-attr]
        _CN.CNContactOrganizationNameKey,  # type: ignore[union-attr]
        _CN.CNContactIdentifierKey,  # type: ignore[union-attr]
    ]


def _get_store() -> Any:
    if not _HAS_CONTACTS:
        raise RuntimeError("pyobjc-framework-Contacts not installed — requires macOS")
    return _CN.CNContactStore.alloc().init()  # type: ignore[union-attr]


def _contact_to_dict(contact: Any) -> dict:
    emails = [
        str(e.value()) for e in (contact.emailAddresses() or [])
    ]
    phones = [
        str(p.value().stringValue()) for p in (contact.phoneNumbers() or [])
    ]
    given = str(contact.givenName()) if contact.givenName() else ""
    family = str(contact.familyName()) if contact.familyName() else ""
    org = str(contact.organizationName()) if contact.organizationName() else None
    return {
        "id": str(contact.identifier()),
        "name": f"{given} {family}".strip() or org or "",
        "given_name": given or None,
        "family_name": family or None,
        "organization": org,
        "emails": emails,
        "phones": phones,
    }


# ---------------------------------------------------------------------------
# Sync implementations (run in a thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _sync_search(query: str) -> list[dict]:
    store = _get_store()
    keys = _fetch_keys()
    predicate = _CN.CNContact.predicateForContactsMatchingName_(query)  # type: ignore[union-attr]
    contacts = store.unifiedContactsMatchingPredicate_keysToFetch_error_(
        predicate, keys, None
    )
    return [_contact_to_dict(c) for c in (contacts or [])]


def _sync_get(contact_id: str) -> Optional[dict]:
    store = _get_store()
    keys = _fetch_keys()
    contact = store.unifiedContactWithIdentifier_keysToFetch_error_(
        contact_id, keys, None
    )
    if contact is None:
        return None
    return _contact_to_dict(contact)


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def contacts_search(query: str) -> list[dict]:
    """Search macOS Contacts by name, email, or phone number.

    Args:
        query: Search string (partial name, email, or phone)

    Returns:
        List of matching contacts with id, name, emails, and phones.
    """
    return await asyncio.to_thread(_sync_search, query)


@mcp.tool()
async def contacts_get(id: str) -> Optional[dict]:
    """Fetch a single contact by its identifier.

    Args:
        id: The CNContact identifier string

    Returns:
        Contact dict, or None if not found.
    """
    return await asyncio.to_thread(_sync_get, id)


if __name__ == "__main__":
    mcp.run()
