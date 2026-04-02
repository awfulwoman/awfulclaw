# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**awfulclaw** — an autonomous AI agent that communicates via Telegram (and a REST API), invokes Claude via the `claude` CLI subprocess, and stores working memory in SQLite. Runs natively on a dedicated Mac Mini, supervised by launchd. No Docker, no API key — auth comes from the locally installed `claude` CLI.

## Status

This project is being reimplemented from scratch. The design spec is complete; implementation has not started.

## Layout

```
DESIGN.md          # complete design spec — the primary reference for implementation
PHILOSOPHY.md      # design values and principles
CLAUDE.md          # this file
legacy/            # old codebase — do not reference during implementation (see DESIGN.md)
```

## Key documents

- **`DESIGN.md`** — the implementation spec. Read this first. It covers the full architecture: package layout, component breakdown, middleware pipeline, MCP servers, skills, service management, deployment, and implementation phases.
- **`PHILOSOPHY.md`** — design values: data philosophy, policy layers, governance model, self-modification limits.

## Implementation

This is a clean-room reimplementation. See the "Implementation Approach" section in `DESIGN.md` for the rules:

1. Delete `legacy/` on the implementation branch before writing any new code
2. Build `agent/` from scratch using `DESIGN.md` as the spec
3. Do not reference the old codebase — if something is unclear, improve the spec
