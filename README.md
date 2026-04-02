# awfulclaw

An autonomous AI agent that communicates via Telegram (and a REST API), invokes Claude via the `claude` CLI subprocess, and stores working memory in SQLite. Runs natively on a dedicated Mac Mini, supervised by launchd. No Docker, no API key — auth comes from the locally installed `claude` CLI.

## Status

This project is being reimplemented from scratch. See `DESIGN.md` for the full architecture spec and `PHILOSOPHY.md` for design values and principles.

## Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)
- Claude CLI installed and authenticated (`claude` command available)

## Documentation

| Document | Purpose |
|----------|---------|
| `DESIGN.md` | Complete implementation spec — architecture, components, phases |
| `PHILOSOPHY.md` | Design values, data philosophy, governance model |
| `CLAUDE.md` | Guidance for Claude Code when working in this repo |
