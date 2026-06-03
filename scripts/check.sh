#!/usr/bin/env bash
# Verify full stack: platform + bridge + asterisk + frontend.
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
  ok "EXTERNAL_IP=${EXTERNAL_IP:-?} (use this as SIP server on your phone)"
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
if docker logs gemini_bridge 2>&1 | grep -q "ARI websocket connected"; then
  ok "bridge connected to ARI (docker logs gemini_bridge)"
else
  fail "bridge not connected to ARI yet"
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
if [ "$ERR" -eq 0 ]; then
  echo -e "${GREEN}All checks passed.${NC}"
  echo ""
  echo "Admin UI:    http://localhost  (login: admin@aura.ai / changeme123)"
  echo "Platform API http://localhost:8000"
  echo ""
  echo "Phone must be on the SAME Wi-Fi as this PC (not mobile data)."
  echo ""
  echo "  SIP server:  ${EXTERNAL_IP:-<host-ip>}"
  echo "  Port:        5060 UDP"
  echo "  Username:    1000"
  echo "  Password:    1000pass"
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
