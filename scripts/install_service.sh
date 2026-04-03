#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

mkdir -p "$PROJECT_DIR/logs"

PLIST_DEST="$HOME/Library/LaunchAgents/ai.awfulclaw.agent.plist"

sed \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$PROJECT_DIR/launchd/ai.awfulclaw.agent.plist" > "$PLIST_DEST"

launchctl load "$PLIST_DEST"

echo "awfulclaw service installed and started."
echo "Logs: $PROJECT_DIR/logs/"
