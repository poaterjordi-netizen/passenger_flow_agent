#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_DOMAIN="gui/$(id -u)"
LIVE_LABEL="com.metro-passenger-flow-agent.live"
BRIDGE_LABEL="com.metro-passenger-flow-agent.assistant-bridge"
LIVE_PLIST="$HOME/Library/LaunchAgents/$LIVE_LABEL.plist"
BRIDGE_PLIST="$HOME/Library/LaunchAgents/$BRIDGE_LABEL.plist"
BRIDGE_MANAGER="$PROJECT_ROOT/scripts/manage_assistant_bridge.sh"
DB_TUNNEL_MANAGER="${METRO_LIVE_TUNNEL_MANAGER:-$HOME/.config/metro-passenger-flow-agent/manage-db-tunnel.sh}"
LOCAL_URL="http://127.0.0.1:5173/real-shadow/"
PUBLIC_URL="https://metro.9m-zx.com/real-shadow/"

public_ready() {
  [[ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$PUBLIC_URL" || true)" == "200" ]]
}

is_loaded() {
  launchctl print "$USER_DOMAIN/$1" >/dev/null 2>&1
}

load_agent() {
  local label="$1"
  local plist="$2"
  if ! is_loaded "$label"; then
    [[ -r "$plist" ]] || {
      echo "Missing installed LaunchAgent: $plist" >&2
      return 2
    }
    launchctl bootstrap "$USER_DOMAIN" "$plist"
  fi
  launchctl enable "$USER_DOMAIN/$label"
  launchctl kickstart -k "$USER_DOMAIN/$label"
}

start() {
  load_agent "$LIVE_LABEL" "$LIVE_PLIST"
  load_agent "$BRIDGE_LABEL" "$BRIDGE_PLIST"
  for _ in {1..120}; do
    if curl -fsS --max-time 2 "$LOCAL_URL" >/dev/null 2>&1 &&
      "$BRIDGE_MANAGER" status >/dev/null 2>&1 &&
      "$DB_TUNNEL_MANAGER" status >/dev/null 2>&1 &&
      public_ready; then
      echo "Real-shadow is ready: $PUBLIC_URL"
      return 0
    fi
    sleep 0.5
  done
  echo "Real-shadow did not become ready within 60 seconds." >&2
  status || true
  return 1
}

stop() {
  if is_loaded "$BRIDGE_LABEL"; then
    launchctl bootout "$USER_DOMAIN/$BRIDGE_LABEL"
  fi
  echo "Public reverse bridge stopped. The local read-only service was left running."
}

status() {
  local failed=0
  if is_loaded "$LIVE_LABEL" && curl -fsS --max-time 3 "$LOCAL_URL" >/dev/null; then
    echo "Local governed UI: ready"
  else
    echo "Local governed UI: unavailable" >&2
    failed=1
  fi
  if is_loaded "$BRIDGE_LABEL" && "$BRIDGE_MANAGER" status >/dev/null 2>&1; then
    echo "Encrypted reverse bridge: ready"
  else
    echo "Encrypted reverse bridge: unavailable" >&2
    failed=1
  fi
  if [[ -x "$DB_TUNNEL_MANAGER" ]] &&
    "$DB_TUNNEL_MANAGER" status >/dev/null 2>&1; then
    echo "Private database tunnel: ready"
  else
    echo "Private database tunnel: unavailable" >&2
    failed=1
  fi
  if public_ready; then
    echo "Public external-test ingress: ready"
  else
    echo "Public external-test ingress: unavailable" >&2
    failed=1
  fi
  return "$failed"
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *)
    echo "Usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac
