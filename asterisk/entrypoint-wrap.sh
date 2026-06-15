#!/bin/sh
set -e

# Load LAN IP written by ./start.sh (required for physical phones).
if [ -f /run/host.env ]; then
  # shellcheck disable=SC1091
  . /run/host.env
fi

for ext in 1001 1002 1003 1004 1005 1006 1007 1008 1009 1010; do
  eval "SIP_PASS_${ext}=\${SIP_PASS_${ext}:-${ext}pass}"
done

DIDWW_USER="${DIDWW_SIP_USER:-86vbvm130t}"
DIDWW_PASS="${DIDWW_SIP_SECRET:-}"
DIDWW_FROM_DOMAIN="${DIDWW_FROM_DOMAIN:-${EXTERNAL_IP:-}}"

if [ -n "${EXTERNAL_IP}" ]; then
  PJSIP_NAT="external_media_address=${EXTERNAL_IP}
external_signaling_address=${EXTERNAL_IP}"
  RTP_NAT="externaddr=${EXTERNAL_IP}"
  MEDIA_LINE="media_address=${EXTERNAL_IP}"
else
  PJSIP_NAT=""
  RTP_NAT=""
  MEDIA_LINE=""
  echo "asterisk-entrypoint: WARNING EXTERNAL_IP unset — run ./start.sh up -d for phone audio" >&2
fi

# shellcheck disable=SC2016
awk -v pjsip="$PJSIP_NAT" -v rtp="$RTP_NAT" -v media="$MEDIA_LINE" '
  /@EXTERNAL_IP_LINES@/ { print pjsip; next }
  /@EXTERNADDR_LINE@/ { print rtp; next }
  /@MEDIA_ADDRESS_LINE@/ { print media; next }
  { print }
' /templates/pjsip.conf.template > /etc/asterisk/pjsip.conf

SED_PASS=""
for ext in 1001 1002 1003 1004 1005 1006 1007 1008 1009 1010; do
  eval "pass=\$SIP_PASS_${ext}"
  SED_PASS="${SED_PASS}s|@SIP_PASS_${ext}@|${pass}|g; "
done
# shellcheck disable=SC2086
sed -i "${SED_PASS}" /etc/asterisk/pjsip.conf

sed -i \
  -e "s|@DIDWW_USER@|${DIDWW_USER}|g" \
  -e "s|@DIDWW_PASS@|${DIDWW_PASS}|g" \
  -e "s|@DIDWW_FROM_DOMAIN@|${DIDWW_FROM_DOMAIN}|g" \
  /etc/asterisk/pjsip.conf

awk -v rtp="$RTP_NAT" '
  /@EXTERNADDR_LINE@/ { print rtp; next }
  { print }
' /templates/rtp.conf.template > /etc/asterisk/rtp.conf

echo "asterisk-entrypoint: EXTERNAL_IP=${EXTERNAL_IP:-<unset>}"
echo "asterisk-entrypoint: SIP extensions 1000, 1001–1010 (lab prospects)"

exec /usr/local/bin/entrypoint.sh "$@"
