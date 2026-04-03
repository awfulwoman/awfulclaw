#!/usr/bin/env bash
set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/ai.awfulclaw.agent.plist"

launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"

echo "awfulclaw service removed."
