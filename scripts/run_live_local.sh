#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_CONFIG_DIR="${METRO_LIVE_CONFIG_DIR:-$HOME/.config/metro-passenger-flow-agent}"
RUNTIME_DATA_DIR="${METRO_LIVE_DATA_DIR:-$HOME/.local/share/metro-passenger-flow-agent}"
LIVE_ENV_FILE="$RUNTIME_CONFIG_DIR/live.env"
MYSQL_CA="$RUNTIME_CONFIG_DIR/mysql-ca.pem"
MYSQL_PIN_FILE="$RUNTIME_CONFIG_DIR/mysql-leaf.sha256"
SOURCE_REGISTRY="$RUNTIME_CONFIG_DIR/live-source-registry.json"
PREFLIGHT_REPORT="$RUNTIME_DATA_DIR/live-preflight-report.json"
LIVE_WEB_DIST="${METRO_LIVE_WEB_DIST_DIR:-$RUNTIME_DATA_DIR/web-dist}"
HERMES_COMMAND="${METRO_ASSISTANT_HERMES_COMMAND:-$HOME/.local/bin/hermes}"
TUNNEL_MANAGER="${METRO_LIVE_TUNNEL_MANAGER:-$RUNTIME_CONFIG_DIR/manage-db-tunnel.sh}"

if [[ "${METRO_LOCAL_LIVE_SHADOW_ACKNOWLEDGED:-}" != "true" ]]; then
  echo "Refusing to start: set METRO_LOCAL_LIVE_SHADOW_ACKNOWLEDGED=true for this local shadow session." >&2
  exit 2
fi
if [[ ! -x "$HERMES_COMMAND" ]]; then
  echo "Hermes executable is unavailable." >&2
  exit 2
fi
if [[ ! -r "$LIVE_ENV_FILE" ]]; then
  echo "Database connection metadata is unavailable in the external runtime config." >&2
  exit 2
fi
if [[ ! -r "$MYSQL_CA" || ! -r "$MYSQL_PIN_FILE" ]]; then
  echo "MySQL CA or certificate pin is unavailable in the external runtime config." >&2
  exit 2
fi

set -a
# This is a private, operator-owned file outside Git. It contains connection
# metadata only; the password remains in macOS Keychain.
source "$LIVE_ENV_FILE"
set +a
: "${METRO_DB_HOST:?METRO_DB_HOST is required in live.env}"
: "${METRO_DB_PORT:?METRO_DB_PORT is required in live.env}"
: "${METRO_DB_USER:?METRO_DB_USER is required in live.env}"
: "${METRO_DB_NAME:?METRO_DB_NAME is required in live.env}"
if [[ "$METRO_DB_HOST" == "127.0.0.1" && "$METRO_DB_PORT" == "13306" ]]; then
  if [[ ! -x "$TUNNEL_MANAGER" ]]; then
    echo "The private database tunnel manager is unavailable." >&2
    exit 2
  fi
  "$TUNNEL_MANAGER" start
fi
export METRO_DB_PASSWORD="$(security find-generic-password -a "$METRO_DB_USER" -s com.metro-passenger-flow-agent.mysql -w)"
export METRO_DB_SSL_CA="$MYSQL_CA"
export METRO_DB_TLS_CERT_SHA256="$(tr -d '\r\n' <"$MYSQL_PIN_FILE")"
export METRO_DB_ALLOW_INSECURE_TLS=false

export METRO_API_DATA_MODE=production-shadow
export METRO_AGENT_ENV=local-live-shadow
export METRO_API_AUDIT_DIR="$RUNTIME_DATA_DIR/audits"
export METRO_PRODUCTION_SOURCE_STATUS=approved
export METRO_PRODUCTION_CITY=metroflow-city-unverified
export METRO_PRODUCTION_SOURCE_VERSION=clear-stationflow-day-20230927-live-v1
export METRO_PRODUCTION_TIME_GRAIN=10m
export METRO_PRODUCTION_DEFAULT_START=2023-09-27T06:00:00+08:00
export METRO_PRODUCTION_DEFAULT_END=2023-09-27T07:00:00+08:00
export METRO_PRODUCTION_REGISTRY_PATH="$SOURCE_REGISTRY"
export METRO_LOGICAL_REGISTRY_PATH="$PROJECT_ROOT/config/logical_data_products.json"
export METRO_PRODUCTION_ASSISTANT_ENABLED=true
export METRO_PROMOTION_GATE_PATH="$PROJECT_ROOT/config/production_promotion_gates.json"

export METRO_ACCESS_SUBJECT_ID=local-live-shadow-operator
export METRO_ACCESS_TENANT_OR_DEPARTMENT=local-live-shadow
export METRO_ACCESS_ROLES=shadow-reader
export METRO_ACCESS_ALLOWED_CITIES="$METRO_PRODUCTION_CITY"
export METRO_ACCESS_ALLOWED_METRICS=entries,exits,net_inflow
export METRO_ACCESS_ALLOWED_DATASET_ROLES=actual
export METRO_ACCESS_MAX_TIME_RANGE_HOURS=1
export METRO_ACCESS_ROW_LIMIT=1000
export METRO_ACCESS_EXPORT_POLICY=deny
export METRO_ACCESS_POLICY_SNAPSHOT_ID=local-live-shadow-policy-20260721-v1

export METRO_ASSISTANT_PROVIDER=hermes-codex
export METRO_ASSISTANT_MODEL=gpt-5.6-sol
export METRO_ASSISTANT_HERMES_COMMAND="$HERMES_COMMAND"
export METRO_MODEL_ENDPOINT_POLICY_ID=local-live-shadow-gpt56-sol-egress-v1
export METRO_MODEL_DATA_EGRESS=aggregate-approved
export METRO_MODEL_INTENT_EGRESS=metadata-approved
export METRO_MODEL_ALLOWED_PROVIDER=hermes-openai-codex
export METRO_MODEL_ALLOWED_MODEL=gpt-5.6-sol
export METRO_MODEL_ALLOWED_TARGET_HASH="$(
  cd "$PROJECT_ROOT"
  uv run python - <<'PY'
import os
from metro_agent.assistant.provider import HermesCodexProvider, provider_endpoint_identity
provider = HermesCodexProvider(
    command=os.environ["METRO_ASSISTANT_HERMES_COMMAND"],
    model=os.environ["METRO_ASSISTANT_MODEL"],
)
print(provider_endpoint_identity(provider)["target_hash"])
PY
)"

mkdir -p "$RUNTIME_DATA_DIR"
chmod 700 "$RUNTIME_CONFIG_DIR" "$RUNTIME_DATA_DIR"
cd "$PROJECT_ROOT"
uv run python scripts/prepare_live_shadow.py \
  --registry "$SOURCE_REGISTRY" \
  --report "$PREFLIGHT_REPORT" \
  --city "$METRO_PRODUCTION_CITY" \
  --source-version "$METRO_PRODUCTION_SOURCE_VERSION" \
  --start "$METRO_PRODUCTION_DEFAULT_START" \
  --end "$METRO_PRODUCTION_DEFAULT_END" \
  --time-grain "$METRO_PRODUCTION_TIME_GRAIN"

export METRO_API_ACCESS_TOKEN="${METRO_API_ACCESS_TOKEN:-$(openssl rand -hex 32)}"
export METRO_API_PROXY_TOKEN="$METRO_API_ACCESS_TOKEN"
export METRO_WEB_BASE_PATH="${METRO_WEB_BASE_PATH:-/real-shadow/}"
export VITE_API_URL="${VITE_API_URL:-/real-shadow}"
export VITE_ASSISTANT_TIMEOUT_MS="${VITE_ASSISTANT_TIMEOUT_MS:-180000}"
export VITE_DEPLOYMENT_PROFILE="${VITE_DEPLOYMENT_PROFILE:-real-shadow}"

if [[ "${METRO_LIVE_EVALUATE_ONLY:-false}" == "true" ]]; then
  LIVE_EVALUATION_OUTPUT="${METRO_LIVE_EVALUATION_OUTPUT:-$RUNTIME_DATA_DIR/live-gpt56-shadow-ranked.json}"
  LIVE_EVALUATION_QUESTION="${METRO_LIVE_EVALUATION_QUESTION:-查询2023年9月27日6点到7点进站客流最高的3个车站}"
  uv run python scripts/evaluate_live_gpt_shadow.py \
    --question "$LIVE_EVALUATION_QUESTION" \
    --output "$LIVE_EVALUATION_OUTPUT"
  exit 0
fi

DB_TUNNEL_WATCHDOG_PID=""

maintain_database_tunnel() {
  while true; do
    if ! "$TUNNEL_MANAGER" status >/dev/null 2>&1; then
      echo "Database tunnel is unavailable; attempting a bounded restart." >&2
      if ! "$TUNNEL_MANAGER" start; then
        echo "Database tunnel restart failed; retrying in 15 seconds." >&2
      fi
    fi
    sleep 15
  done
}

cleanup() {
  [[ -n "$DB_TUNNEL_WATCHDOG_PID" ]] &&
    kill "$DB_TUNNEL_WATCHDOG_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$DB_TUNNEL_WATCHDOG_PID" ]] &&
    wait "$DB_TUNNEL_WATCHDOG_PID" 2>/dev/null || true
  wait "${WEB_PID:-}" "${API_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uv run metro-agent-api &
API_PID=$!
for _ in {1..50}; do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 0.1
done
if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "API failed to start." >&2
  exit 1
fi

# Keep the live preview outside clients/web/dist. A routine developer build
# uses "/" as its base and must not be able to overwrite the running
# /real-shadow/ assets.
npm --prefix clients/web run build -- --outDir "$LIVE_WEB_DIST" --emptyOutDir
npm --prefix clients/web run preview -- \
  --outDir "$LIVE_WEB_DIST" \
  --host 127.0.0.1 \
  --port 5173 \
  --strictPort &
WEB_PID=$!
if [[ "$METRO_DB_HOST" == "127.0.0.1" && "$METRO_DB_PORT" == "13306" ]]; then
  maintain_database_tunnel &
  DB_TUNNEL_WATCHDOG_PID=$!
fi
echo "Live local shadow is running: http://127.0.0.1:5173/real-shadow/"
wait "$API_PID" "$WEB_PID"
