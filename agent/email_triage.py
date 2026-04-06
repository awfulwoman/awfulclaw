"""Email triage pipeline — three-tier filtering to minimise external model usage.

Tier 1: Header rules (pure Python) — bulk/newsletter detection
Tier 2: Local model (qwen3) — routine vs escalate classification
Tier 3: External model — handled by CheckinHandler on escalated items
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.store import Store

log = logging.getLogger(__name__)

_BULK_HEADERS = {"list-unsubscribe", "list-id", "list-post"}
_BULK_PRECEDENCE = {"bulk", "list", "junk"}


def parse_local_model_verdict(raw: str) -> tuple[str, str]:
    """Extract verdict and summary from local model response.

    Looks for a JSON object anywhere in the response. Defaults to
    ("escalate", <raw text>) if parsing fails or verdict is unrecognised.
    """
    match = re.search(r"\{[^{}]+\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            verdict = data.get("verdict", "").lower()
            summary = str(data.get("summary", raw.strip()))
            if verdict in ("routine", "escalate"):
                return verdict, summary
        except json.JSONDecodeError:
            pass
    return "escalate", raw.strip()


def merge_triage_results(
    existing: dict[str, list],
    new: dict[str, list],
) -> dict[str, list]:
    """Merge a new triage batch into accumulated results without mutating existing."""
    result: dict[str, list] = {}
    for key in ("newsletters", "routine", "escalate"):
        result[key] = list(existing.get(key, [])) + list(new.get(key, []))
    return result


_TRIAGE_KV_KEY = "email_triage"

_LOCAL_MODEL_PROMPT = """\
Classify this email. Reply with only a JSON object: {{"verdict": "routine", "summary": "..."}} or {{"verdict": "escalate", "summary": "..."}}.

"routine" = transactional, automated, no action needed (deliveries, order confirmations, bank alerts, flight check-ins).
"escalate" = personal correspondence, requests, decisions needed, anything unusual.

From: {sender}
Subject: {subject}
Body snippet: {snippet}"""


class EmailTriageJob:
    """Three-tier email triage pipeline.

    imap_run, imap_read, get_headers, local_model_call are injected so they
    can be replaced with mocks in tests. In production, main.py provides real
    implementations backed by the IMAP MCP server and Ollama HTTP API.
    """

    def __init__(
        self,
        store: "Store",
        ollama_url: str,
        ollama_model: str,
        imap_run: Callable[[], Awaitable[list[dict[str, Any]]]],
        imap_read: Callable[[str], Awaitable[str]],
        get_headers: Optional[Callable[[str], Awaitable[dict[str, str]]]] = None,
        local_model_call: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> None:
        self._store = store
        self._ollama_url = ollama_url
        self._ollama_model = ollama_model
        self._imap_run = imap_run
        self._imap_read = imap_read
        self._get_headers = get_headers or self._fetch_headers_stub
        self._local_model_call = local_model_call or self._call_ollama

    async def _fetch_headers_stub(self, uid: str) -> dict[str, str]:
        return {}

    async def _call_ollama(self, prompt: str) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.post(
                f"{self._ollama_url}/api/generate",
                json={"model": self._ollama_model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "")

    async def run(self) -> None:
        emails = await self._imap_run()
        if not emails:
            return

        all_uids = [e["uid"] for e in emails]
        unseen_uids = set(await self._store.filter_unseen_email_uids(all_uids))
        new_emails = [e for e in emails if e["uid"] in unseen_uids]
        if not new_emails:
            return

        newsletters: list[str] = []
        routine: list[str] = []
        escalate: list[dict[str, str]] = []

        for email in new_emails:
            uid = email["uid"]
            subject = email.get("subject", "(no subject)")
            sender = email.get("from", "")
            try:
                headers = await self._get_headers(uid)
                if is_bulk(headers):
                    newsletters.append(subject)
                    continue

                body = await self._imap_read(uid)
                snippet = body[:200].strip()
                prompt = _LOCAL_MODEL_PROMPT.format(
                    sender=sender, subject=subject, snippet=snippet
                )
                raw = await self._local_model_call(prompt)
                verdict, summary = parse_local_model_verdict(raw)
                if verdict == "routine":
                    routine.append(summary)
                else:
                    escalate.append({"uid": uid, "from": sender, "subject": subject, "summary": summary})
            except Exception:
                log.exception("Error triaging email uid=%s", uid)
                escalate.append({"uid": uid, "from": sender, "subject": subject, "summary": subject})

        existing_raw = await self._store.kv_get(_TRIAGE_KV_KEY)
        existing = json.loads(existing_raw) if existing_raw else {}
        merged = merge_triage_results(
            existing,
            {"newsletters": newsletters, "routine": routine, "escalate": escalate},
        )
        await self._store.kv_set(_TRIAGE_KV_KEY, json.dumps(merged))
        await self._store.mark_email_uids_seen(list(unseen_uids))


def is_bulk(headers: dict[str, str]) -> bool:
    """Return True if email headers indicate bulk/automated mail."""
    normalised = {k.lower(): v for k, v in headers.items()}
    if any(h in normalised for h in _BULK_HEADERS):
        return True
    if normalised.get("precedence", "").lower() in _BULK_PRECEDENCE:
        return True
    if "auto-submitted" in normalised:
        return True
    return False
