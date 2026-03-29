#!/usr/bin/env bash
set -euo pipefail

for label in ai.awfulclaw.agent ai.awfulclaw.watcher; do
    PLIST="$HOME/Library/LaunchAgents/${label}.plist"
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
done

echo "awfulclaw service removed."
