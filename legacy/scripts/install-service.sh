#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

UV_PATH="$(which uv 2>/dev/null || true)"
if [[ -z "$UV_PATH" ]]; then
    echo "Error: uv not found on PATH. Install uv first: https://docs.astral.sh/uv/" >&2
    exit 1
fi

mkdir -p "$PROJECT_DIR/logs"
touch /tmp/awfulclaw_reload_debounce

_install_plist() {
    local src="$1"
    local dest="$HOME/Library/LaunchAgents/$(basename "$src")"
    sed \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__UV_PATH__|$UV_PATH|g" \
        -e "s|__PATH__|$PATH|g" \
        "$src" > "$dest"
    launchctl load "$dest"
}

_install_plist "$SCRIPT_DIR/ai.awfulclaw.agent.plist"
_install_plist "$SCRIPT_DIR/ai.awfulclaw.watcher.plist"

echo "awfulclaw service installed and started (with file watcher)."
