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

PLIST_DEST="$HOME/Library/LaunchAgents/ai.awfulclaw.agent.plist"

sed \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__UV_PATH__|$UV_PATH|g" \
    "$PROJECT_DIR/launchd/ai.awfulclaw.agent.plist" > "$PLIST_DEST"

launchctl load "$PLIST_DEST"

echo "awfulclaw service installed and started."
echo "Logs: $PROJECT_DIR/logs/"
