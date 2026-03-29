"""Calls the claude CLI via subprocess, or the Anthropic SDK for vision messages."""

from __future__ import annotations

import base64
import subprocess

from awfulclaw import config


def chat(
    messages: list[dict[str, str]],
    system: str,
    image_data: bytes | None = None,
    image_mime: str | None = None,
) -> str:
    """Invoke claude and return the assistant reply text.

    If *image_data* is provided the Anthropic SDK is used directly (vision path).
    Otherwise the claude CLI subprocess is used.
    """
    if image_data is not None:
        return _chat_sdk(messages, system, image_data, image_mime or "image/jpeg")
    return _chat_cli(messages, system)


def _chat_cli(messages: list[dict[str, str]], system: str) -> str:
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


def _chat_sdk(
    messages: list[dict[str, str]],
    system: str,
    image_data: bytes,
    image_mime: str,
) -> str:
    """Use the Anthropic SDK to send a message with an image on the last user turn."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package is required for image support. "
            "Install it with: uv add anthropic"
        ) from exc

    client = anthropic.Anthropic()
    b64 = base64.standard_b64encode(image_data).decode()

    sdk_messages: list[anthropic.types.MessageParam] = []

    # All but the last message as plain text turns.
    for msg in messages[:-1]:
        role: anthropic.types.MessageParamTypedDict = (  # type: ignore[assignment]
            "user" if msg["role"] == "user" else "assistant"
        )
        sdk_messages.append({"role": role, "content": msg["content"]})

    # Last message gets the image appended.
    last = messages[-1]
    last_content: list[anthropic.types.ContentBlockParam] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_mime,  # type: ignore[typeddict-item]
                "data": b64,
            },
        },
        {"type": "text", "text": last["content"]},
    ]
    sdk_messages.append({"role": "user", "content": last_content})  # type: ignore[arg-type]

    response = client.messages.create(
        model=config.get_model(),
        max_tokens=4096,
        system=system,
        messages=sdk_messages,  # type: ignore[arg-type]
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_blocks).strip()


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
