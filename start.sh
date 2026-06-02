#!/usr/bin/env bash
# Start the Gemini phone agent stack (always run this instead of bare docker compose).
set -euo pipefail
cd "$(dirname "$0")"
"$(dirname "$0")/scripts/ensure-host-env.sh"
exec docker compose --env-file .env --env-file .host.env "$@"
