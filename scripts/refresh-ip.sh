#!/usr/bin/env bash
# Refresh LAN IP + SIP .host.env and recreate Asterisk (e.g. after DHCP change).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENVIRONMENT="${DEPLOY_ENV:-${APP_ENV:-local}}"
if [ "$#" -gt 0 ]; then
  case "$1" in
    local|staging|stage|prod|production)
      ENVIRONMENT="$1"
      shift
      ;;
  esac
fi

case "$ENVIRONMENT" in
  local)
    COMPOSE_ENV="local"
    DEFAULT_SIP_PORT=5060
    DEFAULT_ENV_FILE=".env"
    ;;
  staging|stage)
    COMPOSE_ENV="staging"
    DEFAULT_SIP_PORT=5061
    DEFAULT_ENV_FILE=".env.staging"
    ;;
  prod|production)
    COMPOSE_ENV="prod"
    DEFAULT_SIP_PORT=5060
    DEFAULT_ENV_FILE=".env.prod"
    ;;
  *)
    echo "ERROR: Unknown environment '${ENVIRONMENT}'. Use local, staging, or prod." >&2
    exit 1
    ;;
esac

export DEPLOY_ENV="$COMPOSE_ENV"
export DEFAULT_SIP_PORT
export APP_ENV_FILE="${APP_ENV_FILE:-$DEFAULT_ENV_FILE}"
export HOST_ENV_FILE=".host.${COMPOSE_ENV}.env"
if [ ! -f "$APP_ENV_FILE" ]; then
  echo "ERROR: Environment file '${APP_ENV_FILE}' not found for ${COMPOSE_ENV}." >&2
  exit 1
fi
"$ROOT/scripts/ensure-host-env.sh"

set -a
# shellcheck disable=SC1091
[ -f "$APP_ENV_FILE" ] && . "$APP_ENV_FILE"
# shellcheck disable=SC1091
[ -f "$HOST_ENV_FILE" ] && . "./$HOST_ENV_FILE"
set +a

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found." >&2
  exit 1
fi

COMPOSE_FILES=(-f docker-compose.yml -f "docker-compose.${COMPOSE_ENV}.yml" -p "aura_${COMPOSE_ENV}")
echo "Using Docker Compose environment: ${COMPOSE_ENV}"
echo "Environment file: ${APP_ENV_FILE}"

echo "Recreating asterisk with EXTERNAL_IP=${EXTERNAL_IP}…"
"${COMPOSE[@]}" "${COMPOSE_FILES[@]}" up -d --force-recreate asterisk
echo "Done. Update Zoiper SIP server to: ${EXTERNAL_IP}:${SIP_PORT:-5060}"
