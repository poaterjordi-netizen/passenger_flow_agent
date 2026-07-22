#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${METRO_LIVE_PATH:-$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"
export METRO_LOCAL_LIVE_SHADOW_ACKNOWLEDGED=true

exec /usr/bin/caffeinate -is /bin/bash "$PROJECT_ROOT/scripts/run_live_local.sh"
