#!/usr/bin/env bash
# Refresh LAN IP + SIP .host.env and recreate Asterisk (e.g. after DHCP change).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
"$ROOT/scripts/ensure-host-env.sh"

set -a
# shellcheck disable=SC1091
[ -f .env ] && . ./.env
# shellcheck disable=SC1091
[ -f .host.env ] && . ./.host.env
set +a

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found." >&2
  exit 1
fi

echo "Recreating asterisk with EXTERNAL_IP=${EXTERNAL_IP}…"
"${COMPOSE[@]}" up -d --force-recreate asterisk
echo "Done. Update Zoiper SIP server to: ${EXTERNAL_IP}:${SIP_PORT:-5060}"
