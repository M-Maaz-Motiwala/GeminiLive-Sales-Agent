# DIDWW trunk setup — quick checklist

Your stack is configured for:

| Item | Value |
|------|-------|
| Public IP (whitelist at DIDWW) | `110.38.169.3` |
| Server private IP | `172.16.100.235` |
| DID | `+1 (210) 729-7915` / `+12107297915` |
| Outbound SIP host | `out.didww.com` |
| Outbound username | `86vbvm130t` |
| PJSIP outbound peer | `didww_trunk` |
| PJSIP inbound peer | `didww_in` (matches DIDWW Voice-IN SBC IPs) |

## 1. DIDWW portal — outbound trunk

1. **Outbound Trunks** → your trunk → **Allowed SIP IPs**: add `110.38.169.3`
2. **Allowed RTP IPs**: add `110.38.169.3` (same public IP)
3. Click the **key icon** (Credentials) — copy the **password** if shown
4. Paste into `.env`: `DIDWW_SIP_SECRET=<password>` (leave empty only if IP-only auth is enabled)
5. Confirm host is `out.didww.com`

## 2. DIDWW portal — inbound (Voice-IN)

Route DID `12107297915` to your Asterisk:

- Destination: `sip:110.38.169.3:5060` (UDP)
- Or as configured by DIDWW support for your account

Inbound calls arrive from DIDWW SBC IPs (already in `pjsip.conf.template` `didww_in` identify section).

## 3. Server firewall

On `172.16.100.235` (and edge firewall if any):

| Port | Protocol | Purpose |
|------|----------|---------|
| 5060 | UDP | SIP |
| 10000–10050 | UDP | RTP |
| 80 | TCP | Admin UI |
| 8088 | TCP | **Do not expose** — bridge only (Docker internal) |

## 4. Deploy on the VPS (not your local PC)

```bash
cd /path/to/agenticai_sales_agent
./start.sh up -d --build
./start.sh up -d --force-recreate asterisk
./scripts/check.sh
```

Verify:

```bash
docker exec asterisk asterisk -rx "pjsip show endpoint didww_trunk"
docker exec asterisk asterisk -rx "pjsip show endpoint didww_in"
docker exec asterisk asterisk -rx "dialplan show from-trunk"
docker exec asterisk grep external_media_address /etc/asterisk/pjsip.conf
# Must show: external_media_address=110.38.169.3
```

## 5. Test calls

**Inbound:** Call `+1 210 729 7915` from a mobile → AI should answer.

**Outbound:** Admin → Outbound → dial a real mobile number (E.164 `+1...`).

**Lab (optional):** Set `OUTBOUND_MODE=lab` in `.env` to test with Zoiper extensions again.

## 6. Troubleshooting

| Symptom | Check |
|---------|-------|
| Outbound 401/403 | Add `DIDWW_SIP_SECRET` from portal; confirm `110.38.169.3` whitelisted |
| Inbound never rings | DIDWW Voice-IN routing → `110.38.169.3:5060` |
| No audio | `external_media_address=110.38.169.3`; RTP ports open |
| Wrong caller ID | `OUTBOUND_TRUNK_CALLER_ID=+12107297915` |
