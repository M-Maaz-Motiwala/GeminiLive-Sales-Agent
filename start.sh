#!/usr/bin/env bash
# Start the Gemini phone agent stack (always run this instead of bare docker compose).
set -euo pipefail
cd "$(dirname "$0")"
"$(dirname "$0")/scripts/ensure-host-env.sh"
# shellcheck disable=SC1091
. ./.host.env
COMPOSE=(docker compose --env-file .env --env-file .host.env)
if [ "${IP_CHANGED:-0}" = "1" ] && [[ " $* " == *" up "* ]]; then
  echo "Recreating asterisk for EXTERNAL_IP=${EXTERNAL_IP}…"
  "${COMPOSE[@]}" up -d --force-recreate asterisk
fi
exec "${COMPOSE[@]}" "$@"
