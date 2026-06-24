#!/usr/bin/env bash
# Start the Gemini phone agent stack (always run this instead of bare docker compose).
set -euo pipefail
cd "$(dirname "$0")"
"$(dirname "$0")/scripts/ensure-host-env.sh"

# Export .env + .host.env for compose ${VAR} substitution (older docker lacks --env-file).
set -a
# shellcheck disable=SC1091
[ -f .env ] && . ./.env
# shellcheck disable=SC1091
[ -f .host.env ] && . ./.host.env
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

if [ "${IP_CHANGED:-0}" = "1" ] && [[ " $* " == *" up "* ]]; then
  echo "Recreating asterisk for EXTERNAL_IP=${EXTERNAL_IP}…"
  "${COMPOSE[@]}" up -d --force-recreate asterisk
fi
exec "${COMPOSE[@]}" "$@"
