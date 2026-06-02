#!/usr/bin/env bash
# Verify bridge + asterisk are running correctly.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
ok() { echo -e "${GREEN}OK${NC}  $*"; }
fail() { echo -e "${RED}FAIL${NC} $*"; ERR=1; }
ERR=0

echo "=== Docker containers ==="
if docker ps --format '{{.Names}}\t{{.Status}}' | grep -q gemini_bridge; then
  ok "gemini_bridge running"
else
  fail "gemini_bridge not running"
fi
if docker ps --format '{{.Names}}\t{{.Status}}' | grep -q asterisk; then
  ok "asterisk running"
else
  fail "asterisk not running"
fi

echo ""
echo "=== Phone SIP address (.host.env) ==="
if [ -f .host.env ]; then
  # shellcheck disable=SC1091
  . ./.host.env
  ok "EXTERNAL_IP=${EXTERNAL_IP:-?} (use this as SIP server on your phone)"
else
  fail ".host.env missing — run: ./start.sh up -d"
fi

echo ""
echo "=== Bridge health ==="
if curl -sf --connect-timeout 2 http://127.0.0.1:8000/health >/dev/null; then
  ok "http://127.0.0.1:8000/health"
else
  fail "bridge HTTP health check"
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
if docker logs gemini_bridge 2>&1 | grep -q "ARI websocket connected"; then
  ok "bridge connected to ARI (see docker logs gemini_bridge)"
else
  fail "bridge not connected to ARI yet"
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
if [ "$ERR" -eq 0 ]; then
  echo -e "${GREEN}All checks passed.${NC}"
  echo ""
  echo "Phone must be on the SAME Wi-Fi as this PC (not mobile data)."
  echo ""
  echo "  SIP server:  ${EXTERNAL_IP:-<host-ip>}"
  echo "  Port:        5060 UDP"
  echo "  Username:    1000"
  echo "  Password:    1000pass"
  echo ""
  echo "  Dial 600  = echo test (hear your own voice — try this FIRST)"
  echo "  Dial 700  = Gemini AI agent"
else
  echo -e "${RED}Some checks failed.${NC} Fix issues above, then: ./start.sh up -d --build"
  exit 1
fi
