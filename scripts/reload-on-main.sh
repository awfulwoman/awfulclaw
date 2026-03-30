#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

BRANCH="$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null || echo "")"

if [[ "$BRANCH" != "main" ]]; then
    echo "Branch is '${BRANCH}' — skipping restart." >&2
    exit 0
fi

DEBOUNCE_FILE="/tmp/awfulclaw_reload_debounce"
DEBOUNCE_SECONDS=60

now=$(date +%s)

# Check debounce window
if [[ -f "$DEBOUNCE_FILE" ]]; then
    last=$(stat -f %m "$DEBOUNCE_FILE" 2>/dev/null || echo 0)
    if (( now - last < DEBOUNCE_SECONDS )); then
        echo "Debouncing (last restart $((now - last))s ago) — skipping." >&2
        exit 0
    fi
fi

# Only restart if a core .py file changed.
# Excludes __pycache__ (build artifacts) and modules/ (hot-reloaded at runtime — no restart needed).
# Does NOT exclude mcp/ — MCP servers are spawned as subprocesses by the claude CLI and cannot
# be hot-reloaded, so changes there require a full agent restart.
CHANGED_PY=$(find "$PROJECT_DIR/awfulclaw" -name "*.py" \
    -not -path "*/__pycache__/*" \
    -not -path "*/modules/*" \
    -newer "$DEBOUNCE_FILE" 2>/dev/null | head -1)

if [[ -z "$CHANGED_PY" ]] && [[ -f "$DEBOUNCE_FILE" ]]; then
    echo "No .py files changed (likely __pycache__ update) — skipping." >&2
    exit 0
fi

touch "$DEBOUNCE_FILE"
echo "Branch is main — restarting awfulclaw service..." >&2
launchctl kickstart -k "gui/$(id -u)/ai.awfulclaw.agent"
echo "Restarted." >&2
