"""Thin wrapper around the Anthropic SDK."""

from __future__ import annotations

import anthropic

from awfulclaw import config


def chat(messages: list[dict[str, str]], system: str) -> str:
    """Call Claude and return the assistant reply text."""
    client = anthropic.Anthropic(auth_token=config.get_auth_token())
    response = client.messages.create(
        model=config.get_model(),
        max_tokens=4096,
        system=system,
        messages=messages,  # type: ignore[arg-type]
    )
    block = response.content[0]
    if block.type != "text":
        return ""
    return block.text
