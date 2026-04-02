"""Memory layer — read/write Markdown files under the memory/ root."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path("memory")


def _resolve(path: str) -> Path:
    """Resolve a relative path under the memory root.

    Raises ValueError if the resolved path escapes the memory root.
    """
    full = (_ROOT / path).resolve()
    root = _ROOT.resolve()
    if not (full == root or str(full).startswith(str(root) + "/")):
        raise ValueError(f"Path escapes memory root: {path!r}")
    return full


def _ensure_root() -> None:
    _ROOT.mkdir(parents=True, exist_ok=True)


def read(path: str) -> str:
    """Return file contents, or empty string if not found."""
    _ensure_root()
    full = _resolve(path)
    if not full.exists():
        return ""
    return full.read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    """Write content to path (relative to memory root), creating dirs as needed."""
    _ensure_root()
    full = _resolve(path)
    full.parent.mkdir(parents=True, exist_ok=True)
    tmp = full.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, full)


def list_files(subdir: str) -> list[str]:
    """Return filenames (not full paths) in a subdirectory."""
    _ensure_root()
    d = _ROOT / subdir
    if not d.exists():
        return []
    return sorted(f.name for f in d.iterdir() if f.is_file())


def search(subdir: str, query: str) -> list[tuple[str, str]]:
    """Substring search over file contents. Returns (filename, matching_line) tuples."""
    _ensure_root()
    d = _ROOT / subdir
    if not d.exists():
        return []
    results: list[tuple[str, str]] = []
    query_lower = query.lower()
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if query_lower in line.lower():
                results.append((f.name, line))
                break  # one match per file
    return results


def search_all(
    query: str, subdirs: list[str] | None = None
) -> list[tuple[str, str]]:
    """Search across all subdirs. Returns (relative_path, matching_line) tuples."""
    _ensure_root()
    if subdirs is None:
        subdirs = []
    results: list[tuple[str, str]] = []
    query_lower = query.lower()
    for subdir in subdirs:
        d = _ROOT / subdir
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(_ROOT)
            for line in f.read_text(encoding="utf-8").splitlines():
                if query_lower in line.lower():
                    results.append((str(rel), line))
                    break  # one match per file
    return results
