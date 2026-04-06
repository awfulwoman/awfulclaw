#!/usr/bin/env bash
set -euo pipefail

launchctl unload "$HOME/Library/LaunchAgents/ai.awfulclaw.agent.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/ai.awfulclaw.agent.plist"

launchctl unload "$HOME/Library/LaunchAgents/ai.awfulclaw.logrotate.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/ai.awfulclaw.logrotate.plist"

launchctl unload "$HOME/Library/LaunchAgents/ai.awfulclaw.web.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/ai.awfulclaw.web.plist"

echo "awfulclaw services removed."
