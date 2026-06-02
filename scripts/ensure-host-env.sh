#!/usr/bin/env bash
# Write .host.env with this machine's LAN IP (for phone SIP/RTP SDP).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IP="${EXTERNAL_IP:-$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')}"
if [ -z "$IP" ]; then
  echo "ERROR: could not detect LAN IP. Set EXTERNAL_IP manually." >&2
  exit 1
fi
printf 'EXTERNAL_IP=%s\n' "$IP" > "$ROOT/.host.env"
echo "Wrote $ROOT/.host.env (EXTERNAL_IP=$IP)"
