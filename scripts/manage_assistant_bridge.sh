#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${METRO_LIVE_CONFIG_DIR:-$HOME/.config/metro-passenger-flow-agent}"
SSH_DIR="$CONFIG_DIR/ssh"
SSH_KEY="${METRO_ASSISTANT_BRIDGE_SSH_KEY:-$SSH_DIR/web-ecs-tunnel-ed25519}"
KNOWN_HOSTS="${METRO_ASSISTANT_BRIDGE_KNOWN_HOSTS:-$SSH_DIR/known_hosts}"
CONTROL_SOCKET="${METRO_ASSISTANT_BRIDGE_CONTROL_SOCKET:-$SSH_DIR/assistant-reverse.control}"
REMOTE_HOST="${METRO_ASSISTANT_BRIDGE_REMOTE_HOST:-182.92.31.179}"
REMOTE_USER="${METRO_ASSISTANT_BRIDGE_REMOTE_USER:-metro-tunnel}"
REMOTE_BIND="${METRO_ASSISTANT_BRIDGE_REMOTE_BIND:-127.0.0.1:18080}"
LOCAL_TARGET="${METRO_ASSISTANT_BRIDGE_LOCAL_TARGET:-127.0.0.1:5173}"

require_runtime_files() {
  [[ -r "$SSH_KEY" ]] || { echo "Assistant bridge SSH key is unavailable." >&2; exit 2; }
  [[ -r "$KNOWN_HOSTS" ]] || { echo "Assistant bridge known_hosts is unavailable." >&2; exit 2; }
  install -d -m 0700 "$SSH_DIR"
}

ssh_common=(
  -i "$SSH_KEY"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$KNOWN_HOSTS"
  -o ExitOnForwardFailure=yes
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
  -o ConnectTimeout=10
)

foreground() {
  require_runtime_files
  rm -f "$CONTROL_SOCKET"
  exec ssh -M -S "$CONTROL_SOCKET" -NT \
    "${ssh_common[@]}" \
    -R "$REMOTE_BIND:$LOCAL_TARGET" \
    "$REMOTE_USER@$REMOTE_HOST"
}

start() {
  require_runtime_files
  if ssh -S "$CONTROL_SOCKET" -O check "$REMOTE_USER@$REMOTE_HOST" >/dev/null 2>&1; then
    echo "Assistant reverse bridge is already running."
    return 0
  fi
  rm -f "$CONTROL_SOCKET"
  ssh -M -S "$CONTROL_SOCKET" -fNT \
    "${ssh_common[@]}" \
    -R "$REMOTE_BIND:$LOCAL_TARGET" \
    "$REMOTE_USER@$REMOTE_HOST"
  status
}

stop() {
  if [[ ! -S "$CONTROL_SOCKET" ]]; then
    echo "Assistant reverse bridge is not running."
    return 0
  fi
  ssh -S "$CONTROL_SOCKET" -O exit "$REMOTE_USER@$REMOTE_HOST" >/dev/null
  rm -f "$CONTROL_SOCKET"
}

status() {
  require_runtime_files
  if [[ -S "$CONTROL_SOCKET" ]] && \
    ssh -S "$CONTROL_SOCKET" -O check "$REMOTE_USER@$REMOTE_HOST" >/dev/null 2>&1; then
    echo "Assistant reverse bridge is running: $REMOTE_BIND -> $LOCAL_TARGET"
    return 0
  fi
  echo "Assistant reverse bridge is not running." >&2
  return 1
}

case "${1:-status}" in
  foreground) foreground ;;
  start) start ;;
  stop) stop ;;
  status) status ;;
  *)
    echo "Usage: $0 {foreground|start|stop|status}" >&2
    exit 2
    ;;
esac
