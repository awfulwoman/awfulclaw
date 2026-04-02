#!/usr/bin/env bash
set -euo pipefail

launchctl kickstart -k "gui/$(id -u)/ai.awfulclaw.agent"
echo "awfulclaw restarted."
