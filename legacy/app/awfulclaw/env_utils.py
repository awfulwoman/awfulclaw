"""Utilities for safely writing to the project .env file."""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_PATH = Path(".env")
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def validate_key(key: str) -> None:
    if not _KEY_RE.match(key):
        raise ValueError(f"Invalid env key {key!r}: must match [A-Z][A-Z0-9_]*")


def set_env_var(key: str, value: str) -> None:
    """Write or update KEY=value in .env atomically.

    Never exposes the existing value — this is intentionally write-only.
    """
    validate_key(key)
    lines: list[str] = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()

    prefix = f"{key}="
    updated = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            new_lines.append(f"{key}={_quote(value)}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key}={_quote(value)}")

    content = "\n".join(new_lines)
    if content and not content.endswith("\n"):
        content += "\n"

    tmp = _ENV_PATH.with_name(".env.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, _ENV_PATH)


def get_env_keys() -> list[str]:
    """Return the key names currently in .env — no values."""
    if not _ENV_PATH.exists():
        return []
    keys: list[str] = []
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.append(key)
    return sorted(keys)


def _quote(value: str) -> str:
    """Quote a .env value if it contains whitespace or special characters."""
    if any(c in value for c in (" ", "\t", "\n", "#", '"', "'")):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
