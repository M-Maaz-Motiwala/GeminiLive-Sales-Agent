# Production Setup: Company Asterisk ↔ Aura Docker Asterisk

**SIP trunk + DID routing — step-by-step guide**

This guide configures your **existing Docker stack** (Asterisk + Bridge + Platform) on a **public server**, connected to your **company's production Asterisk** via a **SIP trunk**. Calls to your DID land on company Asterisk, are forwarded to your Docker Asterisk, and then routed to the Gemini AI agent.

You are **not** moving Asterisk to the company server. You are **not** changing the bridge architecture. You are adding a SIP trunk between the two Asterisk servers.

---

## Table of contents

1. [Architecture overview](#1-architecture-overview)
2. [What stays the same vs what changes](#2-what-stays-the-same-vs-what-changes)
3. [Prerequisites checklist](#3-prerequisites-checklist)
4. [Information to collect before you start](#4-information-to-collect-before-you-start)
5. [Phase 1 — Prepare the public server](#5-phase-1--prepare-the-public-server)
6. [Phase 2 — Configure Aura Docker Asterisk (your server)](#6-phase-2--configure-aura-docker-asterisk-your-server)
7. [Phase 3 — Configure company production Asterisk](#7-phase-3--configure-company-production-asterisk)
8. [Phase 4 — DID routing (inbound PSTN)](#8-phase-4--did-routing-inbound-pstn)
9. [Phase 5 — Outbound calls through company trunk](#9-phase-5--outbound-calls-through-company-trunk)
10. [Phase 6 — Environment variables (.env)](#10-phase-6--environment-variables-env)
11. [Phase 7 — Firewall and security](#11-phase-7--firewall-and-security)
12. [Phase 8 — Start the stack and verify](#12-phase-8--start-the-stack-and-verify)
13. [Phase 9 — Admin UI and agent configuration](#13-phase-9--admin-ui-and-agent-configuration)
14. [Phase 10 — End-to-end test calls](#14-phase-10--end-to-end-test-calls)
15. [Troubleshooting](#15-troubleshooting)
16. [Appendix A — Full config snippets](#appendix-a--full-config-snippets)
17. [Appendix B — Port reference](#appendix-b--port-reference)

---

## 1. Architecture overview

### Call flow — inbound (customer calls your DID)

```
Customer phone (PSTN)
    │
    ▼
SIP Provider / Carrier
    │
    ▼
Company Production Asterisk  ←── DID is assigned here
    │  Dialplan: forward DID → SIP trunk
    ▼
SIP Trunk (UDP 5060) over internet/VPN
    │
    ▼
Aura Docker Asterisk (public server)  ←── your docker-compose stack
    │  Dialplan: Stasis(gemini-agent)
    ▼
gemini_bridge (ARI + RTP :40000–40049)
    │  HTTP /internal/calls/*
    ▼
aura_platform (agents, CRM, sessions)
    │
    ▼
Google Gemini Live API
```

### Call flow — outbound (AI calls a lead)

```
Admin UI / Campaign
    │
    ▼
aura_platform  →  POST /internal/originate
    │
    ▼
gemini_bridge  →  ARI originate
    │
    ▼
Aura Docker Asterisk  →  PJSIP/+E164@company_trunk
    │
    ▼
SIP Trunk
    │
    ▼
Company Production Asterisk  →  PSTN trunk
    │
    ▼
Lead's phone
```

### Internal communication (unchanged from lab)

| From | To | Protocol | Port | Purpose |
|------|-----|----------|------|---------|
| `gemini_bridge` | `asterisk` (Docker) | ARI HTTP + WebSocket | TCP 8088 | Call control, Stasis events |
| `gemini_bridge` | `asterisk` (Docker) | UDP RTP ExternalMedia | 40000–40049 | AI audio (bridge container) |
| `asterisk` (Docker) | Phones / company trunk | SIP + RTP | UDP 5060, 10000–10050 | Caller audio |
| `aura_platform` | `gemini_bridge` | HTTP | TCP 8000 (internal) | Originate, status |
| `gemini_bridge` | `aura_platform` | HTTP | TCP 8000 (internal) | Agent config, transcripts |

**Key point:** The bridge always talks to **your Docker Asterisk** (`ARI_HOST=asterisk`). Company Asterisk is only a SIP hop for PSTN in/out.

---

## 2. What stays the same vs what changes

| Component | Lab (today) | Production (this guide) |
|-----------|-------------|-------------------------|
| Docker stack | Same machine / LAN | Public server (VPS/cloud) |
| Asterisk | In Docker | **Still in Docker** |
| Bridge → Asterisk | `ARI_HOST=asterisk` | **Same** — no change |
| `EXTERNAL_MEDIA_HOST` | `bridge` (Docker DNS) | **Same** — stays `bridge` |
| Inbound trigger | Zoiper dials ext 700 | DID → company Asterisk → trunk → `Stasis(gemini-agent)` |
| Outbound target | `PJSIP/1001` (lab phone) | `PJSIP/+E164@company_trunk` |
| `OUTBOUND_MODE` | `lab` | `trunk` |
| `EXTERNAL_IP` | Auto LAN IP | **Public server IP** (fixed) |
| `pjsip.conf` | Extensions 1000–1010 only | **+ company trunk peer** |
| `extensions.conf` | `[internal]` only | **+ `[from-company-trunk]` context** |

---

## 3. Prerequisites checklist

### Public server

- [ ] Linux VPS or cloud VM (Ubuntu 22.04+ recommended)
- [ ] Public static IPv4 address (e.g. `203.0.113.50`)
- [ ] Root or sudo access
- [ ] Docker Engine 24+ and Docker Compose v2 installed
- [ ] Ports available (see [Appendix B](#appendix-b--port-reference))
- [ ] Domain name optional (for HTTPS admin UI later)

### Company Asterisk team

- [ ] Access to production Asterisk config (or a ticket to IT)
- [ ] Company Asterisk public IP or VPN IP
- [ ] Permission to create a SIP trunk peer on company Asterisk
- [ ] At least one DID assigned on company Asterisk
- [ ] Outbound PSTN allowed through company trunk (for campaigns)

### API keys and secrets

- [ ] `GEMINI_API_KEY` from https://aistudio.google.com/apikey
- [ ] `PINECONE_API_KEY` from https://app.pinecone.io/ (for RAG)
- [ ] Strong `JWT_SECRET_KEY` and `BRIDGE_INTERNAL_TOKEN` for production

### Network agreement with IT

- [ ] Company Asterisk can send SIP (UDP 5060) to your public server IP
- [ ] Company Asterisk can send RTP (UDP 10000–10050) to your public server IP
- [ ] Your Docker Asterisk can send SIP/RTP back to company Asterisk IP
- [ ] Optional but recommended: restrict SIP to company IP only (firewall allowlist)

---

## 4. Information to collect before you start

Fill this table in before configuring anything:

| Item | Your value | Example |
|------|------------|---------|
| Public server IP | `________________` | `203.0.113.50` |
| Company Asterisk IP | `________________` | `198.51.100.10` |
| Company Asterisk SIP port | `________________` | `5060` |
| Your DID (E.164) | `________________` | `+15551234567` |
| Outbound caller ID | `________________` | `+15551234567` |
| Trunk auth username (if any) | `________________` | `aura_trunk` |
| Trunk auth password (if any) | `________________` | `long-random-secret` |
| Trunk peer name (your side) | `________________` | `company_trunk` |
| Trunk peer name (company side) | `________________` | `aura_server` |
| VPN in use? (Y/N) | `________________` | Tailscale / none |

---

## 5. Phase 1 — Prepare the public server

### Step 1.1 — Provision the server

1. Create a VPS (AWS EC2, DigitalOcean, Hetzner, Azure VM, etc.).
2. Choose a region close to your company Asterisk (lower latency = better voice quality).
3. Assign a **static public IPv4**.
4. Note the IP — you will use it everywhere as `YOUR_PUBLIC_IP`.

### Step 1.2 — Install Docker

```bash
# Ubuntu example
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates

# Install Docker (official script)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Log out and back in so docker group applies
```

Verify:

```bash
docker --version
docker compose version
```

### Step 1.3 — Clone the repository

```bash
cd /opt
sudo git clone <your-repo-url> agenticai_sales_agent
sudo chown -R $USER:$USER agenticai_sales_agent
cd agenticai_sales_agent
```

### Step 1.4 — Create production `.env`

```bash
cp .env.example .env
nano .env   # or vim / your editor
```

Set at minimum (full list in [Phase 6](#10-phase-6--environment-variables-env)):

```env
GEMINI_API_KEY=your_real_key
PINECONE_API_KEY=your_real_key
JWT_SECRET_KEY=<64-char-random-string>
BRIDGE_INTERNAL_TOKEN=<64-char-random-string>
ADMIN_PASSWORD=<strong-password>

# CRITICAL: use your public IP, not "auto"
EXTERNAL_IP=203.0.113.50
```

> **Why fixed `EXTERNAL_IP`?** On a public server, `auto` would detect the private VPC IP. Asterisk needs the **public** IP in `external_media_address` so company Asterisk and RTP work correctly.

### Step 1.5 — Open firewall ports on public server

```bash
# UFW example (adjust if using cloud security groups instead)
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # Admin UI
sudo ufw allow 8000/tcp    # API (or restrict to your office IP)
sudo ufw allow 5060/udp    # SIP from company Asterisk
sudo ufw allow 10000:10050/udp  # RTP phone/trunk audio
sudo ufw enable
```

**Do NOT expose port 8088 (ARI) publicly.** Only `gemini_bridge` uses it inside Docker.

If your cloud provider has a security group, mirror the same rules there.

### Step 1.6 — (Optional) Restrict SIP to company IP only

Safer than open `5060` to the world:

```bash
sudo ufw delete allow 5060/udp
sudo ufw allow from 198.51.100.10 to any port 5060 proto udp
sudo ufw allow from 198.51.100.10 to any port 10000:10050 proto udp
```

Replace `198.51.100.10` with company Asterisk IP.

---

## 6. Phase 2 — Configure Aura Docker Asterisk (your server)

Your Asterisk config lives in the `asterisk/` folder. At container start, `entrypoint-wrap.sh` generates `pjsip.conf` from `pjsip.conf.template` using `EXTERNAL_IP`.

### Step 2.1 — Add company trunk to `pjsip.conf.template`

Open `asterisk/pjsip.conf.template`.

Scroll to the **end of the file** (after extension 1010) and append the block below.

Replace placeholders:

- `COMPANY_ASTERISK_IP` → company server IP
- `TRUNK_USER` / `TRUNK_PASS` → shared credentials (agree with IT)
- `company_trunk` → peer name (must match `OUTBOUND_TRUNK_NAME` in `.env`)

```ini
; =============================================================================
; SIP TRUNK — Company Production Asterisk
; Inbound: company Asterisk sends calls here (context from-company-trunk)
; Outbound: Aura dials PJSIP/+E164@company_trunk
; =============================================================================

[company_trunk_auth]
type=auth
auth_type=userpass
username=TRUNK_USER
password=TRUNK_PASS

[company_trunk]
type=aor
max_contacts=1
contact=sip:COMPANY_ASTERISK_IP:5060
qualify_frequency=60

[company_trunk]
type=endpoint
transport=transport-udp
context=from-company-trunk
disallow=all
allow=ulaw
allow=alaw
auth=company_trunk_auth
outbound_auth=company_trunk_auth
aors=company_trunk
direct_media=no
force_rport=yes
rtp_symmetric=yes
rewrite_contact=yes
timers=no
@MEDIA_ADDRESS_LINE@

[company_trunk]
type=identify
endpoint=company_trunk
match=COMPANY_ASTERISK_IP
```

**What each section does:**

| Section | Purpose |
|---------|---------|
| `auth` | Username/password for outbound calls to company Asterisk |
| `aor` | Where to send outbound SIP INVITEs |
| `endpoint` | Trunk settings; `context=from-company-trunk` handles inbound |
| `identify` | Match inbound SIP from company IP to this endpoint (no registration needed) |

### Step 2.2 — Add inbound dialplan to `extensions.conf`

Open `asterisk/extensions.conf`.

Add this **new context** at the end of the file (keep existing `[internal]` unchanged):

```ini
; =============================================================================
; Inbound calls from company Asterisk trunk (DID forwarded here)
; =============================================================================
[from-company-trunk]

; Log caller ID and dialed number for debugging
exten => _X.,1,NoOp(=== Inbound from company trunk ===)
 same => n,NoOp(CallerID: ${CALLERID(all)} DID: ${EXTEN})
 same => n,Stasis(gemini-agent)
 same => n,Hangup()

; Specific DID (optional — if company sends full E.164 as extension)
exten => _+X.,1,NoOp(=== Inbound DID ${EXTEN} ===)
 same => n,Stasis(gemini-agent)
 same => n,Hangup()
```

**Important rules:**

- Do **not** call `Answer()` before `Stasis()` — the bridge handles ringing and answering.
- Do **not** add `Stasis(gemini-agent, some-slug)` unless you want a fixed agent. Leaving slug empty lets the platform `callback_router` pick the right sales agent.

### Step 2.3 — Verify ARI config (no changes usually needed)

File `asterisk/ari.conf` should already contain:

```ini
[gemini]
type=user
read_only=no
password=gemini123
```

For production, change `gemini123` to a strong password and update `ARI_PASS` in `.env` to match.

### Step 2.4 — Verify HTTP/ARI is internal only

File `asterisk/http.conf`:

```ini
[general]
enabled=yes
bindaddr=0.0.0.0
bindport=8088
```

Port `8088` is published in `docker-compose.yml` but should be **firewalled off** from the public internet. Only the `gemini_bridge` container needs it (via Docker network `voip`).

### Step 2.5 — Recreate Asterisk after config changes

Every time you edit `pjsip.conf.template` or `extensions.conf`:

```bash
./start.sh up -d --force-recreate asterisk
```

Wait ~15 seconds, then verify:

```bash
docker exec asterisk asterisk -rx "pjsip show endpoint company_trunk"
docker exec asterisk asterisk -rx "dialplan show from-company-trunk"
```

Expected:

- Endpoint `company_trunk` shows `Context: from-company-trunk`
- Dialplan shows `Stasis(gemini-agent)`

---

## 7. Phase 3 — Configure company production Asterisk

Give this section to your Asterisk admin / IT team. They configure **their** server — not yours.

### Step 3.1 — Create trunk peer pointing to your public server

On **company Asterisk**, add a PJSIP trunk to your Aura server.

Replace:

- `YOUR_PUBLIC_IP` → your Docker server public IP
- `TRUNK_USER` / `TRUNK_PASS` → same credentials as Step 2.1
- `aura_server` → peer name on company side (their choice)

```ini
[aura_trunk_auth]
type=auth
auth_type=userpass
username=TRUNK_USER
password=TRUNK_PASS

[aura_server]
type=aor
contact=sip:YOUR_PUBLIC_IP:5060
qualify_frequency=60

[aura_server]
type=endpoint
transport=transport-udp
context=from-aura-trunk
disallow=all
allow=ulaw
allow=alaw
outbound_auth=aura_trunk_auth
aors=aura_server
direct_media=no
force_rport=yes
rtp_symmetric=yes
rewrite_contact=yes

[aura_server]
type=identify
endpoint=aura_server
match=YOUR_PUBLIC_IP
```

Reload on company Asterisk:

```bash
asterisk -rx "module reload res_pjsip.so"
asterisk -rx "pjsip show endpoint aura_server"
```

### Step 3.2 — Allow inbound SIP from your server (company firewall)

Company firewall must allow:

| Direction | Protocol | Ports | Source/Dest |
|-----------|----------|-------|-------------|
| Company → Aura | UDP | 5060 | Dest: `YOUR_PUBLIC_IP` |
| Company → Aura | UDP | 10000–10050 | Dest: `YOUR_PUBLIC_IP` |
| Aura → Company | UDP | 5060 | Dest: `COMPANY_ASTERISK_IP` |
| Aura → Company | UDP | RTP range | Dest: `COMPANY_ASTERISK_IP` |

### Step 3.3 — Test trunk connectivity (before DID)

From **company Asterisk**, originate a test call to your server:

```bash
asterisk -rx "channel originate PJSIP/700@aura_server application Echo"
```

On **your server**, watch logs:

```bash
docker logs -f asterisk
docker logs -f gemini_bridge
```

If trunk works, you should see SIP activity in Asterisk logs. Extension `700` hits `Stasis(gemini-agent)` and the AI should answer.

If this fails, fix trunk/firewall before configuring DID.

---

## 8. Phase 4 — DID routing (inbound PSTN)

### Step 4.1 — Understand where the DID lives

The DID is assigned to **company Asterisk** (via their SIP provider). Company Asterisk must forward calls for that DID to your trunk peer `aura_server`.

### Step 4.2 — Company dialplan — route DID to Aura trunk

On **company Asterisk**, in the inbound context (often `from-trunk`, `from-pstn`, or `public`):

**Option A — Route a specific DID:**

```ini
[from-trunk]
exten => +15551234567,1,NoOp(Route DID to Aura AI)
 same => n,Dial(PJSIP/+15551234567@aura_server,60)
 same => n,Hangup()
```

**Option B — Route all inbound to Aura (single DID tenant):**

```ini
[from-trunk]
exten => _X.,1,NoOp(Forward to Aura)
 same => n,Dial(PJSIP/${EXTEN}@aura_server,60)
 same => n,Hangup()
```

**Option C — Route to extension 700 on Aura (simpler):**

```ini
[from-trunk]
exten => +15551234567,1,NoOp(Route DID to Aura ext 700)
 same => n,Dial(PJSIP/700@aura_server,60)
 same => n,Hangup()
```

Option C is easiest: company always dials `700@aura_server`, which hits your existing fleet inbound logic.

### Step 4.3 — What Aura receives

When company forwards the call, your Asterisk receives a SIP INVITE. The `identify` section matches company IP → `company_trunk` endpoint → `from-company-trunk` context → `Stasis(gemini-agent)`.

### Step 4.4 — Caller ID preservation

Company Asterisk should pass the original PSTN caller ID in the SIP `From` / `P-Asserted-Identity` header. Your bridge reads this for callback routing (matching prior outbound sessions).

Ask IT to confirm:

```ini
; On company side Dial() — do not override caller ID
same => n,Dial(PJSIP/700@aura_server,60,b(options))
```

---

## 9. Phase 5 — Outbound calls through company trunk

### Step 5.1 — Company Asterisk must allow outbound from Aura

On **company Asterisk**, add an outbound context for calls arriving from your trunk:

```ini
[from-aura-trunk]
; Calls originated by Aura Docker Asterisk (outbound campaigns)
exten => _+X.,1,NoOp(Outbound from Aura to ${EXTEN})
 same => n,Dial(PJSIP/${EXTEN}@their_pstn_trunk,60)
 same => n,Hangup()

exten => _1NXXNXXXXXX,1,NoOp(Outbound US 10-digit)
 same => n,Dial(PJSIP/+${EXTEN}@their_pstn_trunk,60)
 same => n,Hangup()
```

Replace `their_pstn_trunk` with company Asterisk's real SIP provider trunk name.

### Step 5.2 — Set trunk mode in `.env`

```env
OUTBOUND_MODE=trunk
OUTBOUND_TRUNK_NAME=company_trunk
OUTBOUND_TRUNK_CALLER_ID=+15551234567
OUTBOUND_DEFAULT_COUNTRY_CODE=1
```

The platform will dial: `PJSIP/+15559876543@company_trunk`

### Step 5.3 — How outbound works internally

1. Admin clicks **Dial** in UI
2. Platform `endpoint_resolver.py` builds `PJSIP/+E164@company_trunk`
3. Bridge ARI originates: `POST /ari/channels` with `app=gemini-agent`, `appArgs=riley,outbound,{lead_id}`
4. Your Docker Asterisk sends SIP INVITE to company Asterisk
5. Company Asterisk routes to PSTN via their provider trunk
6. On answer → `StasisStart` → Gemini session (same as inbound)

---

## 10. Phase 6 — Environment variables (.env)

Complete production `.env` reference for this setup:

```env
# =============================================================================
# AI
# =============================================================================
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_TEXT_MODEL=gemini-2.5-flash
GEMINI_VOICE=Zephyr

# =============================================================================
# PLATFORM
# =============================================================================
JWT_SECRET_KEY=change_to_long_random_string
ADMIN_EMAIL=admin@yourcompany.com
ADMIN_PASSWORD=strong_password_here

PINECONE_API_KEY=your_pinecone_key
PINECONE_INDEX_NAME=aura-knowledge

# =============================================================================
# BRIDGE ↔ PLATFORM (must match)
# =============================================================================
BRIDGE_INTERNAL_TOKEN=change_to_long_random_token
PLATFORM_URL=http://platform:8000
BRIDGE_URL=http://bridge:8000

# =============================================================================
# ASTERISK ARI — bridge → Docker asterisk (unchanged)
# =============================================================================
ARI_HOST=asterisk
ARI_PORT=8088
ARI_USER=gemini
ARI_PASS=strong_ari_password_here
ARI_APP=gemini-agent

# =============================================================================
# NAT / SIP — PUBLIC SERVER
# =============================================================================
EXTERNAL_IP=203.0.113.50
EXTERNAL_MEDIA_HOST=bridge
SIP_PORT=5060

# =============================================================================
# OUTBOUND — trunk through company Asterisk
# =============================================================================
OUTBOUND_MODE=trunk
OUTBOUND_TRUNK_NAME=company_trunk
OUTBOUND_TRUNK_CALLER_ID=+15551234567
OUTBOUND_DEFAULT_COUNTRY_CODE=1
MAX_CONCURRENT_OUTBOUND=5

# =============================================================================
# CONCURRENCY
# =============================================================================
MAX_CONCURRENT_CALLS=5
RTP_PORT_BASE=40000
RTP_PORT_COUNT=50

# =============================================================================
# COMPLIANCE
# =============================================================================
OUTBOUND_CALL_WINDOW_ENABLED=true
OUTBOUND_CALL_TIMEZONE=America/New_York
OUTBOUND_CALL_HOUR_START=9
OUTBOUND_CALL_HOUR_END=18
```

After editing `.env`:

```bash
./start.sh up -d --build
```

---

## 11. Phase 7 — Firewall and security

### Your public server

| Port | Expose publicly? | Who needs access |
|------|------------------|------------------|
| 22/tcp | Your IP only | SSH admin |
| 80/tcp | Yes (or via CDN) | Admin UI |
| 8000/tcp | Your IP or VPN | API direct access |
| 5060/udp | Company IP only | Company Asterisk SIP |
| 10000–10050/udp | Company IP only | RTP audio |
| 8088/tcp | **No** | Bridge only (Docker internal) |
| 40000–40049/udp | **No** | Bridge RTP (Docker internal) |

### Secrets to rotate for production

- [ ] `ARI_PASS` — change from default `gemini123`
- [ ] `BRIDGE_INTERNAL_TOKEN` — long random string
- [ ] `JWT_SECRET_KEY` — long random string
- [ ] `ADMIN_PASSWORD` — strong password
- [ ] Trunk `TRUNK_PASS` — shared with company IT only

### HTTPS (recommended)

Put nginx or Caddy in front of port 80 with Let's Encrypt for the admin UI. The frontend container already proxies `/api` to the platform.

---

## 12. Phase 8 — Start the stack and verify

### Step 8.1 — First start

```bash
cd /opt/agenticai_sales_agent
./start.sh up -d --build
```

`start.sh` runs `ensure-host-env.sh` which writes `.host.env` with your fixed `EXTERNAL_IP`.

### Step 8.2 — Run automated checks

```bash
./scripts/check.sh
```

All items should show **OK**. Lab phone registration checks (1001/1002) may show **WARN** in production — that is fine if you are not using Zoiper.

### Step 8.3 — Verify Docker containers

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected running: `aura_frontend`, `aura_platform`, `gemini_bridge`, `asterisk`, `aura_postgres`, `aura_redis`, `aura_celery`.

### Step 8.4 — Verify ARI and bridge connection

```bash
curl -s -u gemini:YOUR_ARI_PASS http://127.0.0.1:8088/ari/applications | python3 -m json.tool
```

Look for `"name": "gemini-agent"` — means bridge WebSocket is connected.

### Step 8.5 — Verify company trunk endpoint

```bash
docker exec asterisk asterisk -rx "pjsip show endpoint company_trunk"
```

Check:

- `Endpoint: company_trunk` exists
- `Context: from-company-trunk`
- `Allow: (ulaw|alaw)`

### Step 8.6 — Verify NAT lines in generated pjsip.conf

```bash
docker exec asterisk grep external_media_address /etc/asterisk/pjsip.conf
```

Must show your **public IP**, not a private `172.x` or `10.x` address.

### Step 8.7 — Verify platform health

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/system/info | python3 -m json.tool
```

Check `outbound_mode` is `trunk`.

### Step 8.8 — Verify outbound status

```bash
curl -s http://127.0.0.1:8000/api/outbound/status
```

(Log in via UI first if auth required, or use admin token.)

---

## 13. Phase 9 — Admin UI and agent configuration

### Step 9.1 — Log in

Open `http://YOUR_PUBLIC_IP` (or your domain).

Default credentials (change immediately):

- Email: `admin@aura.ai`
- Password: value of `ADMIN_PASSWORD` in `.env`

### Step 9.2 — Configure inbound agent routing

Inbound calls from DID use `Stasis(gemini-agent)` with **no agent slug**. The platform picks an agent via `callback_router`:

1. If caller previously received an outbound call → route to that agent (callback)
2. Else if agent has matching `inbound_extension` → use that agent
3. Else pick first idle sales/outbound_sales agent

In **Admin → Agents**, for each agent you want to handle inbound:

- Set **Inbound extension** if you want DID-specific routing (e.g. `700`)
- Ensure agent is **Active**
- Type: `sales` or `outbound_sales`

### Step 9.3 — Configure outbound agent

- Use agent **Riley** (or your outbound persona) for campaigns
- Upload knowledge base documents if needed (Admin → Documents)

### Step 9.4 — Create a campaign (optional)

1. Admin → Campaigns → New campaign
2. Assign outbound agent
3. Upload leads CSV with E.164 phones (`+15559876543`)
4. Start campaign when trunk is verified

### Step 9.5 — DNC and call window

- Admin → Leads → mark DNC numbers
- `.env` call window settings enforce dialing hours

---

## 14. Phase 10 — End-to-end test calls

### Test 1 — Echo (local sanity, optional)

If you still have a softphone pointed at your server:

- Dial **600** → echo test (confirms SIP + RTP work)

### Test 2 — Direct Stasis (from company trunk)

Company IT runs:

```bash
asterisk -rx "channel originate PJSIP/700@aura_server application Playback demo-congrats"
```

Or without playback — should hit Gemini:

```bash
asterisk -rx "channel originate PJSIP/700@aura_server extension 700@aura_server"
```

Watch:

```bash
docker logs -f gemini_bridge
```

You should see `StasisStart`, Gemini session open, and audio.

### Test 3 — Inbound DID (full path)

1. Call your DID `+15551234567` from a mobile phone
2. Company Asterisk forwards to your server
3. AI agent should answer after brief ring
4. Check Admin → Sessions for new **INBOUND** session with transcript

### Test 4 — Outbound via UI

1. Admin → Outbound → select agent → enter a test mobile number
2. Click **Dial now**
3. Your phone should ring with caller ID `+15551234567`
4. Check Admin → Sessions for **OUTBOUND** session

### Test 5 — Campaign dial

1. Create campaign with one test lead
2. Start campaign
3. Verify call connects and disposition is recorded

### What to capture if something fails

```bash
# Your server
docker logs --tail 200 asterisk
docker logs --tail 200 gemini_bridge
docker logs --tail 100 aura_platform

# Enable SIP debug (temporary)
docker exec asterisk asterisk -rx "pjsip set logger on"
docker exec asterisk asterisk -rvvv
```

Ask company IT for their Asterisk logs for the same timestamp.

---

## 15. Troubleshooting

### Call connects but no audio (one-way or silence)

| Check | Command / action |
|-------|------------------|
| `EXTERNAL_IP` is public IP | `grep EXTERNAL_IP .host.env` |
| RTP ports open | `sudo ufw status` — 10000–10050 UDP |
| Company can reach RTP | Packet capture: `sudo tcpdump -n udp port 10000` |
| `direct_media=no` on trunk | Both sides |
| NAT lines in pjsip | `docker exec asterisk grep external /etc/asterisk/pjsip.conf` |

### Call drops after ~30 seconds

Classic symptom of wrong `EXTERNAL_IP` or blocked RTP.

1. Set `EXTERNAL_IP=YOUR_PUBLIC_IP` in `.env`
2. `./start.sh up -d --force-recreate asterisk`
3. Confirm `external_media_address=YOUR_PUBLIC_IP` in generated pjsip.conf

### Inbound DID rings but AI never answers

| Check | Fix |
|-------|-----|
| Bridge not connected to ARI | `docker restart gemini_bridge`; check `gemini-agent` in applications |
| Wrong dialplan context | `docker exec asterisk asterisk -rx "dialplan show from-company-trunk"` |
| `Answer()` before Stasis on company side | Remove — bridge must answer via ARI |
| `GEMINI_API_KEY` invalid | Check bridge logs for Gemini errors |

### Outbound fails immediately

| Check | Fix |
|-------|-----|
| `OUTBOUND_MODE=trunk` | `.env` + restart platform |
| `OUTBOUND_TRUNK_NAME` mismatch | Must match `pjsip.conf.template` endpoint name |
| Company rejects outbound | IT must allow `from-aura-trunk` context |
| Invalid phone format | Use E.164: `+15559876543` |

### SIP 403 / 401 authentication errors

- Verify `TRUNK_USER` / `TRUNK_PASS` match on both Asterisk servers
- Reload PJSIP on both sides after password change

### Company trunk shows Unavailable

```bash
docker exec asterisk asterisk -rx "pjsip qualify company_trunk"
docker exec asterisk asterisk -rx "pjsip show endpoint company_trunk"
```

- Check company Asterisk IP in `aor` contact
- Check firewall allows UDP 5060 both directions

### Bridge shows "busy" / 409 on outbound

- `MAX_CONCURRENT_CALLS` reached — wait for active calls to end
- Or increase in `.env` (and `RTP_PORT_COUNT` if needed)

---

## Appendix A — Full config snippets

### A.1 — Your `extensions.conf` (complete production version)

```ini
[general]
static=yes
writeprotect=no
clearglobalvars=no

[globals]

[internal]

exten => 700,1,NoOp(Sales fleet inbound / callback)
 same => n,Stasis(gemini-agent)
 same => n,Hangup()

exten => 701,1,Goto(700,1)
exten => 702,1,Goto(700,1)
exten => 703,1,Goto(700,1)
exten => 704,1,Goto(700,1)

; Extension-to-extension (lab / testing)
exten => 1000,1,NoOp(Calling 1000)
 same => n,Dial(PJSIP/1000,30)
 same => n,Hangup()

; ... extensions 1001-1010 unchanged ...

exten => 600,1,NoOp(Echo test)
 same => n,Answer()
 same => n,Echo()
 same => n,Hangup()

[from-company-trunk]
exten => _X.,1,NoOp(Inbound from company trunk CID ${CALLERID(all)} EXTEN ${EXTEN})
 same => n,Stasis(gemini-agent)
 same => n,Hangup()
```

### A.2 — Company Asterisk minimal inbound + outbound

```ini
; --- Trunk to Aura (see Phase 3) ---

[from-trunk]
exten => +15551234567,1,NoOp(DID to Aura AI)
 same => n,Dial(PJSIP/700@aura_server,60)
 same => n,Hangup()

[from-aura-trunk]
exten => _+X.,1,NoOp(Aura outbound ${EXTEN})
 same => n,Dial(PJSIP/${EXTEN}@pstn_provider_trunk,60)
 same => n,Hangup()
```

---

## Appendix B — Port reference

### Public server (host)

| Port | Protocol | Service | Expose to |
|------|----------|---------|-----------|
| 80 | TCP | Admin UI (nginx) | Internet (or VPN) |
| 8000 | TCP | Platform API | Internet (or VPN) |
| 5060 | UDP | Asterisk SIP | Company Asterisk IP |
| 10000–10050 | UDP | Asterisk RTP (caller/trunk audio) | Company Asterisk IP |
| 8088 | TCP | Asterisk ARI | **Docker internal only** |

### Docker internal (voip network)

| Port | Protocol | Service |
|------|----------|---------|
| 8088 | TCP | Asterisk ARI (bridge connects) |
| 40000–40049 | UDP | Bridge RTP (ExternalMedia per call) |
| 8000 | TCP | Bridge HTTP |

---

## Quick reference — who configures what

| Task | Who | Where |
|------|-----|-------|
| Deploy Docker stack | You | Public server |
| Set `EXTERNAL_IP` to public IP | You | `.env` |
| Add `company_trunk` peer | You | `asterisk/pjsip.conf.template` |
| Add `from-company-trunk` dialplan | You | `asterisk/extensions.conf` |
| Open firewall 5060 + RTP | You | Public server |
| Create `aura_server` trunk peer | Company IT | Company Asterisk |
| Route DID to `aura_server` | Company IT | Company dialplan |
| Allow Aura outbound to PSTN | Company IT | Company dialplan |
| Set `OUTBOUND_MODE=trunk` | You | `.env` |
| Assign agents, campaigns | You | Admin UI |

---

## Related files in this repository

| File | Role |
|------|------|
| `docker-compose.yml` | Service orchestration |
| `start.sh` | Always use instead of bare `docker compose` |
| `.env` / `.env.example` | All secrets and telephony mode |
| `asterisk/pjsip.conf.template` | SIP endpoints + trunk (generated at start) |
| `asterisk/extensions.conf` | Dialplan including Stasis |
| `asterisk/ari.conf` | ARI credentials for bridge |
| `bridge/app/main.py` | ARI + Gemini voice bridge |
| `scripts/check.sh` | Automated stack verification |
| `README.md` | Lab setup and general docs |

---

*Last updated for split deployment: Company Production Asterisk ↔ Aura Docker Asterisk via SIP trunk.*
