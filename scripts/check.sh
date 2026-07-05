#!/usr/bin/env bash
# Verify full stack: platform + bridge + asterisk + frontend.
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
    DEFAULT_ENV_FILE=".env"
    PLATFORM_CONTAINER=aura_platform
    BRIDGE_CONTAINER=gemini_bridge
    ASTERISK_CONTAINER=asterisk
    FRONTEND_CONTAINER=aura_frontend
    POSTGRES_CONTAINER=aura_postgres
    REDIS_CONTAINER=aura_redis
    PLATFORM_PORT=8000
    FRONTEND_PORT=8080
    ARI_PORT=8088
    ASTERISK_RTP_START=10000
    ASTERISK_RTP_END=10050
    ;;
  staging|stage)
    COMPOSE_ENV="staging"
    DEFAULT_ENV_FILE=".env.staging"
    PLATFORM_CONTAINER=aura_staging_platform
    BRIDGE_CONTAINER=aura_staging_bridge
    ASTERISK_CONTAINER=aura_staging_asterisk
    FRONTEND_CONTAINER=aura_staging_frontend
    POSTGRES_CONTAINER=aura_staging_postgres
    REDIS_CONTAINER=aura_staging_redis
    PLATFORM_PORT=8001
    FRONTEND_PORT=8081
    ARI_PORT=8089
    ASTERISK_RTP_START=10060
    ASTERISK_RTP_END=10110
    ;;
  prod|production)
    COMPOSE_ENV="prod"
    DEFAULT_ENV_FILE=".env.prod"
    PLATFORM_CONTAINER=aura_prod_platform
    BRIDGE_CONTAINER=aura_prod_bridge
    ASTERISK_CONTAINER=aura_prod_asterisk
    FRONTEND_CONTAINER=aura_prod_frontend
    POSTGRES_CONTAINER=aura_prod_postgres
    REDIS_CONTAINER=aura_prod_redis
    PLATFORM_PORT=8000
    FRONTEND_PORT=8080
    ARI_PORT=8088
    ASTERISK_RTP_START=10000
    ASTERISK_RTP_END=10050
    ;;
  *)
    echo "ERROR: Unknown environment '${ENVIRONMENT}'. Use local, staging, or prod." >&2
    exit 1
    ;;
esac

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
ok() { echo -e "${GREEN}OK${NC}  $*"; }
warn() { echo -e "${YELLOW}WARN${NC} $*"; }
fail() { echo -e "${RED}FAIL${NC} $*"; ERR=1; }
ERR=0

APP_ENV_FILE="${APP_ENV_FILE:-$DEFAULT_ENV_FILE}"
HOST_ENV_FILE=".host.${COMPOSE_ENV}.env"
if [ -f "$APP_ENV_FILE" ]; then
  # shellcheck disable=SC1091
  . "$APP_ENV_FILE"
fi

echo "=== Docker containers ==="
for c in "$PLATFORM_CONTAINER" "$BRIDGE_CONTAINER" "$ASTERISK_CONTAINER" "$FRONTEND_CONTAINER" "$POSTGRES_CONTAINER" "$REDIS_CONTAINER"; do
  if docker ps --format '{{.Names}}' | grep -qx "$c"; then
    ok "$c running"
  else
    fail "$c not running"
  fi
done

echo ""
echo "=== Phone SIP address ($HOST_ENV_FILE) ==="
if [ -f "$HOST_ENV_FILE" ]; then
  # shellcheck disable=SC1091
  . "./$HOST_ENV_FILE"
  ok "EXTERNAL_IP=${EXTERNAL_IP:-?} (Zoiper SIP server)"
  ok "Port ${SIP_PORT:-5060} UDP · user ${SIP_USER:-1000} · codec ${SIP_CODEC:-PCMU}"
  if [ "${IP_CHANGED:-0}" = "1" ]; then
    echo "  (IP changed this run — Asterisk recreated if you used ./start.sh up)"
  fi
else
  fail "$HOST_ENV_FILE missing — run: ./start.sh up -d"
fi

echo ""
echo "=== Platform API ==="
if curl -sf --connect-timeout 3 "http://127.0.0.1:${PLATFORM_PORT}/health" >/dev/null; then
  ok "http://127.0.0.1:${PLATFORM_PORT}/health (platform)"
else
  fail "platform HTTP health check"
fi

echo ""
echo "=== Admin UI ==="
if curl -sf --connect-timeout 3 "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null; then
  ok "http://127.0.0.1:${FRONTEND_PORT}/ (frontend)"
else
  fail "frontend not reachable on :80"
fi

echo ""
echo "=== ARI (Asterisk REST) ==="
if curl -sf --connect-timeout 2 -u "${ARI_USER:-gemini}:${ARI_PASS:-gemini123}" \
  "http://127.0.0.1:${ARI_PORT}/ari/api-docs/resources.json" >/dev/null; then
  ok "Asterisk ARI on :${ARI_PORT}"
else
  fail "Asterisk ARI not reachable on :${ARI_PORT}"
fi

echo ""
echo "=== Bridge → Asterisk ARI websocket ==="
if curl -sf --connect-timeout 2 -u "${ARI_USER:-gemini}:${ARI_PASS:-gemini123}" \
  "http://127.0.0.1:${ARI_PORT}/ari/applications" 2>/dev/null | grep -q "\"name\": \"${ARI_APP:-gemini-agent}\""; then
  ok "bridge connected to ARI (${ARI_APP:-gemini-agent} registered)"
else
  fail "bridge not connected to ARI yet — wait a few seconds or: docker restart ${BRIDGE_CONTAINER}"
fi

echo ""
echo "=== Bridge health (internal) ==="
if docker exec "$BRIDGE_CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" >/dev/null 2>&1; then
  ok "bridge /health inside container"
else
  fail "bridge health check"
fi

echo ""
echo "=== Asterisk NAT config (phones) ==="
if docker exec "$ASTERISK_CONTAINER" grep -q external_media_address /etc/asterisk/pjsip.conf 2>/dev/null; then
  NAT=$(docker exec "$ASTERISK_CONTAINER" grep external_media_address /etc/asterisk/pjsip.conf)
  ok "pjsip $NAT"
else
  fail "no external_media_address in pjsip.conf — recreate with ./start.sh up -d"
fi

echo ""
echo "=== Asterisk RTP range ==="
if docker exec "$ASTERISK_CONTAINER" grep -q "^rtpstart=${ASTERISK_RTP_START}$" /etc/asterisk/rtp.conf 2>/dev/null &&
   docker exec "$ASTERISK_CONTAINER" grep -q "^rtpend=${ASTERISK_RTP_END}$" /etc/asterisk/rtp.conf 2>/dev/null; then
  ok "rtp ${ASTERISK_RTP_START}-${ASTERISK_RTP_END}"
else
  fail "Asterisk RTP range is not ${ASTERISK_RTP_START}-${ASTERISK_RTP_END} — recreate with ./start.sh ${ENVIRONMENT} up -d --force-recreate asterisk"
fi

echo ""
echo "=== Asterisk SIP extensions ==="
# One CLI call — rapid per-extension "asterisk -rx" races the single-threaded CLI and flakes.
PJSIP_ENDPOINTS=""
for attempt in 1 2 3; do
  PJSIP_ENDPOINTS=$(docker exec "$ASTERISK_CONTAINER" asterisk -rx "pjsip show endpoints" 2>/dev/null || true)
  if echo "$PJSIP_ENDPOINTS" | grep -qE '^ Endpoint:  [0-9]'; then
    break
  fi
  sleep 1
done
for ext in 1000 1001 1002 1003 1004 1005 1006 1007 1008 1009 1010; do
  if echo "$PJSIP_ENDPOINTS" | grep -qE "^ Endpoint:  ${ext}[[:space:]]"; then
    ok "extension ${ext} in pjsip"
  else
    fail "extension ${ext} missing — run: ./start.sh up -d --force-recreate asterisk"
  fi
done

echo ""
echo "=== SIP registrations (lab phones) ==="
for ext in 1001 1002; do
  BLOCK=$(echo "$PJSIP_ENDPOINTS" | awk -v e="$ext" '
    $1 == "Endpoint:" && $2 == e { found=1; next }
    found && /^ Endpoint:/ { exit }
    found && /Contact:/ { print; exit }
  ')
  if [ -z "$BLOCK" ]; then
    fail "extension ${ext} not registered — Zoiper SIP server must be ${EXTERNAL_IP:-<host-ip>}:${SIP_PORT:-5060}"
  elif echo "$BLOCK" | grep -qE '172\.19\.0\.[0-9]+'; then
    # Docker SNAT stores 172.19.0.1; with qualify_frequency=0 inbound/outbound still work.
    if echo "$BLOCK" | grep -qE 'Avail|NonQual'; then
      warn "extension ${ext} Docker NAT contact $(echo "$BLOCK" | awk '{print $2}') (normal in Docker lab; calls OK)"
    else
      fail "extension ${ext} unreachable Docker contact $(echo "$BLOCK" | awk '{print $2}') — re-register Zoiper to ${EXTERNAL_IP:-<host-ip>}"
    fi
  elif echo "$BLOCK" | grep -qF "${EXTERNAL_IP:-}"; then
    ok "extension ${ext} registered $(echo "$BLOCK" | awk '{print $2}')"
  elif echo "$BLOCK" | grep -q 'Avail'; then
    ok "extension ${ext} registered $(echo "$BLOCK" | awk '{print $2}')"
  else
    fail "extension ${ext} stale contact $(echo "$BLOCK" | awk '{print $2}') — re-register Zoiper to ${EXTERNAL_IP:-<host-ip>}"
  fi
done

echo ""
if [ "$ERR" -eq 0 ]; then
  echo -e "${GREEN}All checks passed.${NC}"
  echo ""
  echo "Admin UI:    http://localhost:${FRONTEND_PORT}  (login: admin@aura.ai / changeme123)"
  echo "Platform API http://localhost:${PLATFORM_PORT}"
  echo ""
  echo "Phone must be on the SAME Wi-Fi as this PC (not mobile data)."
  echo ""
  echo "  SIP server:  ${EXTERNAL_IP:-<host-ip>}"
  echo "  Port:        ${SIP_PORT:-5060} UDP"
  echo "  Username:    ${SIP_USER:-1000} (inbound) · 1001–1010 (outbound lab prospects)"
  echo "  Password:    ${SIP_PASS:-1000pass} · {ext}pass for 1001–1010 (override via SIP_PASS_100x in .env)"
  echo "  Codec:       ${SIP_CODEC:-PCMU} (G.711 μ-law)"
  echo ""
  echo "  IP changed?   ./scripts/refresh-ip.sh"
  echo ""
  echo "  Dial 600  = echo test"
  echo "  Dial 700  = sales fleet inbound (callbacks; 701–704 alias to 700)"
else
  echo -e "${RED}Some checks failed.${NC} Fix issues above, then: ./start.sh up -d --build"
  exit 1
fi
