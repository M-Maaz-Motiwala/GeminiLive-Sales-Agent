#!/bin/sh
set -e

# Load LAN IP written by ./start.sh (required for physical phones).
if [ -f /run/host.env ]; then
  # shellcheck disable=SC1091
  . /run/host.env
fi

SIP_PASS_1001="${SIP_PASS_1001:-1001pass}"
SIP_PASS_1002="${SIP_PASS_1002:-1002pass}"

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

sed -i "s|@SIP_PASS_1001@|${SIP_PASS_1001}|g; s|@SIP_PASS_1002@|${SIP_PASS_1002}|g" \
  /etc/asterisk/pjsip.conf

awk -v rtp="$RTP_NAT" '
  /@EXTERNADDR_LINE@/ { print rtp; next }
  { print }
' /templates/rtp.conf.template > /etc/asterisk/rtp.conf

echo "asterisk-entrypoint: EXTERNAL_IP=${EXTERNAL_IP:-<unset>}"
echo "asterisk-entrypoint: SIP extensions 1000, 1001 (${SIP_PASS_1001:+set}), 1002 (${SIP_PASS_1002:+set})"
exec /usr/local/bin/entrypoint.sh "$@"
