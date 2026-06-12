#!/usr/bin/env bash
# Verify full stack: platform + bridge + asterisk + frontend.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
ok() { echo -e "${GREEN}OK${NC}  $*"; }
warn() { echo -e "${YELLOW}WARN${NC} $*"; }
fail() { echo -e "${RED}FAIL${NC} $*"; ERR=1; }
ERR=0

echo "=== Docker containers ==="
for c in aura_platform gemini_bridge asterisk aura_frontend aura_postgres aura_redis; do
  if docker ps --format '{{.Names}}' | grep -qx "$c"; then
    ok "$c running"
  else
    fail "$c not running"
  fi
done

echo ""
echo "=== Phone SIP address (.host.env) ==="
if [ -f .host.env ]; then
  # shellcheck disable=SC1091
  . ./.host.env
  ok "EXTERNAL_IP=${EXTERNAL_IP:-?} (Zoiper SIP server)"
  ok "Port ${SIP_PORT:-5060} UDP · user ${SIP_USER:-1000} · codec ${SIP_CODEC:-PCMU}"
  if [ "${IP_CHANGED:-0}" = "1" ]; then
    echo "  (IP changed this run — Asterisk recreated if you used ./start.sh up)"
  fi
else
  fail ".host.env missing — run: ./start.sh up -d"
fi

echo ""
echo "=== Platform API ==="
if curl -sf --connect-timeout 3 http://127.0.0.1:8000/health >/dev/null; then
  ok "http://127.0.0.1:8000/health (platform)"
else
  fail "platform HTTP health check"
fi

echo ""
echo "=== Admin UI ==="
if curl -sf --connect-timeout 3 http://127.0.0.1/ >/dev/null; then
  ok "http://127.0.0.1/ (frontend)"
else
  fail "frontend not reachable on :80"
fi

echo ""
echo "=== ARI (Asterisk REST) ==="
if curl -sf --connect-timeout 2 -u gemini:gemini123 \
  http://127.0.0.1:8088/ari/api-docs/resources.json >/dev/null; then
  ok "Asterisk ARI on :8088"
else
  fail "Asterisk ARI not reachable on :8088"
fi

echo ""
echo "=== Bridge → Asterisk ARI websocket ==="
if curl -sf --connect-timeout 2 -u gemini:gemini123 \
  http://127.0.0.1:8088/ari/applications 2>/dev/null | grep -q '"name": "gemini-agent"'; then
  ok "bridge connected to ARI (gemini-agent registered)"
else
  fail "bridge not connected to ARI yet — wait a few seconds or: docker restart gemini_bridge"
fi

echo ""
echo "=== Bridge health (internal) ==="
if docker exec gemini_bridge python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" >/dev/null 2>&1; then
  ok "bridge /health inside container"
else
  fail "bridge health check"
fi

echo ""
echo "=== Asterisk NAT config (phones) ==="
if docker exec asterisk grep -q external_media_address /etc/asterisk/pjsip.conf 2>/dev/null; then
  NAT=$(docker exec asterisk grep external_media_address /etc/asterisk/pjsip.conf)
  ok "pjsip $NAT"
else
  fail "no external_media_address in pjsip.conf — recreate with ./start.sh up -d"
fi

echo ""
echo "=== Asterisk SIP extensions ==="
# One CLI call — rapid per-extension "asterisk -rx" races the single-threaded CLI and flakes.
PJSIP_ENDPOINTS=""
for attempt in 1 2 3; do
  PJSIP_ENDPOINTS=$(docker exec asterisk asterisk -rx "pjsip show endpoints" 2>/dev/null || true)
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
  echo "Admin UI:    http://localhost  (login: admin@aura.ai / changeme123)"
  echo "Platform API http://localhost:8000"
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
  echo "  Dial 701  = Maya — Lead Qualifier"
  echo "  Dial 702  = Aria — Trangotech Sales"
  echo "  Dial 703  = Sam — Support FAQ"
  echo "  Dial 700  = first active agent (legacy)"
else
  echo -e "${RED}Some checks failed.${NC} Fix issues above, then: ./start.sh up -d --build"
  exit 1
fi
