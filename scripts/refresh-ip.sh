#!/usr/bin/env bash
# Refresh LAN IP + SIP .host.env and recreate Asterisk (e.g. after DHCP change).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
"$ROOT/scripts/ensure-host-env.sh"
# shellcheck disable=SC1091
. ./.host.env
echo "Recreating asterisk with EXTERNAL_IP=${EXTERNAL_IP}…"
docker compose --env-file .env --env-file .host.env up -d --force-recreate asterisk
echo "Done. Update Zoiper SIP server to: ${EXTERNAL_IP}:${SIP_PORT:-5060}"
