"""Calls the claude CLI via subprocess instead of the Anthropic SDK directly."""

from __future__ import annotations

import subprocess

from awfulclaw import config


def chat(messages: list[dict[str, str]], system: str) -> str:
    """Invoke the claude CLI and return the assistant reply text."""
    prompt = _format_messages(messages)

    cmd = [
        "claude",
        "--print",
        "--no-session-persistence",
        "--system-prompt", system,
        "--model", config.get_model(),
    ]

    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()}")

    return result.stdout.strip()


def _format_messages(messages: list[dict[str, str]]) -> str:
    """Render message history as plain text so the CLI receives full context."""
    if not messages:
        return ""

    # All but the last message become a labelled history block.
    history_parts: list[str] = []
    for msg in messages[:-1]:
        label = "Human" if msg["role"] == "user" else "Assistant"
        history_parts.append(f"{label}: {msg['content']}")

    last = messages[-1]
    if history_parts:
        history = "\n\n".join(history_parts)
        return f"Previous conversation:\n{history}\n\nHuman: {last['content']}"
    return last["content"]
