#!/usr/bin/env bash
# Restart awfulclaw services (agent and/or web).
# Usage: restart.sh [agent|web]   (default: both)
set -euo pipefail

AGENT_LABEL="ai.awfulclaw.agent"
WEB_LABEL="ai.awfulclaw.web"

_restart() {
    local label="$1"
    echo "Restarting $label..."
    launchctl kickstart -k "gui/$(id -u)/$label"
    echo "  done."
}

case "${1:-both}" in
    agent) _restart "$AGENT_LABEL" ;;
    web)   _restart "$WEB_LABEL" ;;
    both)
        _restart "$AGENT_LABEL"
        _restart "$WEB_LABEL"
        ;;
    *)
        echo "Usage: $0 [agent|web|both]" >&2
        exit 1
        ;;
esac
