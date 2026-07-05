#!/usr/bin/env bash
# Start the Gemini phone agent stack (always run this instead of bare docker compose).
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
Usage:
  ./start.sh [local|staging|prod] <docker compose args...>

Examples:
  ./start.sh local up -d --build
  ./start.sh staging up -d --build
  ./start.sh prod up -d --build
  DEPLOY_ENV=staging ./start.sh ps

Default environment is local.
EOF
}

ENVIRONMENT="${DEPLOY_ENV:-${APP_ENV:-local}}"
if [ "$#" -gt 0 ]; then
  case "$1" in
    local|staging|stage|prod|production)
      ENVIRONMENT="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
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
    usage >&2
    exit 1
    ;;
esac

if [ "$#" -eq 0 ]; then
  usage
  exit 1
fi

export DEPLOY_ENV="$COMPOSE_ENV"
export DEFAULT_SIP_PORT
export APP_ENV_FILE="${APP_ENV_FILE:-$DEFAULT_ENV_FILE}"
export HOST_ENV_FILE=".host.${COMPOSE_ENV}.env"
if [ ! -f "$APP_ENV_FILE" ]; then
  echo "ERROR: Environment file '${APP_ENV_FILE}' not found for ${COMPOSE_ENV}." >&2
  echo "       Create it or set APP_ENV_FILE=/path/to/env-file." >&2
  exit 1
fi
# Ensure generated directory exists on host with correct permissions
mkdir -p "asterisk/generated_${COMPOSE_ENV}"

"$(dirname "$0")/scripts/ensure-host-env.sh"

# Export selected env + host env for compose ${VAR} substitution (older docker lacks --env-file).
set -a
# shellcheck disable=SC1091
[ -f "$APP_ENV_FILE" ] && . "$APP_ENV_FILE"
# shellcheck disable=SC1091
[ -f "$HOST_ENV_FILE" ] && . "./$HOST_ENV_FILE"
set +a

# Preflight: docker socket permission (common on fresh VPS installs).
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Cannot access Docker (permission denied or daemon not running)." >&2
  echo "" >&2
  echo "  Fix (recommended) — add your user to the docker group, then log out/in:" >&2
  echo "    sudo usermod -aG docker \"\$(whoami)\"" >&2
  echo "    newgrp docker    # or SSH logout/login" >&2
  echo "" >&2
  echo "  Or run once with sudo:" >&2
  echo "    sudo ./start.sh up -d --build" >&2
  echo "" >&2
  echo "  If daemon is down: sudo systemctl start docker" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found." >&2
  echo "  Install plugin:  sudo apt install docker-compose-plugin" >&2
  echo "  Or standalone:   sudo apt install docker-compose" >&2
  exit 1
fi

COMPOSE_FILES=(-f docker-compose.yml -f "docker-compose.${COMPOSE_ENV}.yml" -p "aura_${COMPOSE_ENV}")
echo "Using Docker Compose environment: ${COMPOSE_ENV}"
echo "Compose files: docker-compose.yml + docker-compose.${COMPOSE_ENV}.yml"
echo "Environment file: ${APP_ENV_FILE}"

if [ "${IP_CHANGED:-0}" = "1" ] && [[ " $* " == *" up "* ]]; then
  echo "Recreating asterisk for EXTERNAL_IP=${EXTERNAL_IP}…"
  "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" up -d --force-recreate asterisk
fi
exec "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" "$@"
