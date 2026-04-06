#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

mkdir -p "$PROJECT_DIR/logs"

# --- Agent service ---
PLIST_DEST="$HOME/Library/LaunchAgents/ai.awfulclaw.agent.plist"
sed \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$PROJECT_DIR/launchd/ai.awfulclaw.agent.plist" > "$PLIST_DEST"
launchctl load "$PLIST_DEST"

# --- Log rotation ---
if ! command -v logrotate &>/dev/null; then
    echo "Installing logrotate via Homebrew..."
    brew install logrotate
fi

LOGROTATE_PLIST="$HOME/Library/LaunchAgents/ai.awfulclaw.logrotate.plist"
cp "$PROJECT_DIR/launchd/ai.awfulclaw.logrotate.plist" "$LOGROTATE_PLIST"
launchctl load "$LOGROTATE_PLIST"

# --- Web service ---
PLIST_WEB="$HOME/Library/LaunchAgents/ai.awfulclaw.web.plist"
sed \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$PROJECT_DIR/launchd/ai.awfulclaw.web.plist" > "$PLIST_WEB"
launchctl load "$PLIST_WEB"

echo "awfulclaw services installed and started."
echo "Logs: $PROJECT_DIR/logs/"
