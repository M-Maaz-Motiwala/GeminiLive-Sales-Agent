# Asterisk + Bridge + Calling Agent Platform

Full-stack **AI phone agent** for LAN testing: register Zoiper on your Wi‑Fi, dial an extension, talk to **Google Gemini Live** with per-agent personas, **CRM tools**, and **Pinecone RAG** knowledge base — all managed from the **Aura admin UI**.

---

## Table of contents

1. [Tech stack](#tech-stack)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Quick start](#quick-start)
5. [Environment variables](#environment-variables)
6. [Zoiper / SIP setup](#zoiper--sip-setup-call-from-your-phone)
7. [What to dial](#what-to-dial)
8. [Outbound calls (lab)](#outbound-calls-lab)
9. [Admin UI walkthrough](#admin-ui-walkthrough)
10. [How to create an agent](#how-to-create-an-agent)
11. [AI knowledge base (RAG)](#ai-knowledge-base-rag)
12. [Project structure](#project-structure)
13. [Useful commands](#useful-commands)
14. [Verification checklist](#verification-checklist)
15. [Troubleshooting](#troubleshooting)

---

## Tech stack

| Layer | Technology | Role |
| ----- | ---------- | ---- |
| **Telephony** | Asterisk 22 (PJSIP, ARI, Stasis) | SIP registration, dialplan, RTP to bridge |
| **Voice bridge** | Python FastAPI + google-genai | ARI websocket, RTP ↔ Gemini Live WebSocket |
| **Platform API** | FastAPI + SQLAlchemy (async) | Agents, sessions, CRM, internal bridge API |
| **Admin UI** | React + Vite + nginx | Agent CRUD, documents, sessions, leads |
| **Database** | PostgreSQL 16 | Agents, sessions, messages, leads, documents |
| **Queue** | Redis 7 + Celery | Async document indexing |
| **Vector DB** | Pinecone (serverless) | RAG embeddings + semantic search |
| **Embeddings** | gemini-embedding-001 (768 dims) | Chunk vectors for knowledge base |
| **Voice AI** | gemini-3.1-flash-live-preview | Real-time speech (configurable per agent) |
| **Orchestration** | Docker Compose | 8 services on one machine |

### Docker services

| Container | Port (host) | Purpose |
| --------- | ----------- | ------- |
| aura_frontend | **80** | Admin UI |
| aura_platform | **8000** | Platform REST API |
| aura_postgres | internal | Database |
| aura_redis | internal | Celery broker |
| aura_celery | internal | Document indexing worker |
| aura_platform_init | one-shot | Migration + seed |
| asterisk | **5060/udp**, **8088**, **10000–10050/udp** | SIP + ARI + RTP |
| gemini_bridge | internal | ARI + Gemini |

---

## Architecture

```
Zoiper (phone, same Wi-Fi)
    │  SIP UDP 5060
    ▼
Asterisk (PJSIP + dialplan 701–704)
    │  Inbound: Stasis(gemini-agent, agent-slug)
    │  Outbound: ARI originate → Stasis(gemini-agent, slug, outbound)
    ▼
gemini_bridge (ARI + RTP :40000 + Gemini Live WS)
    │  POST /internal/calls/*  (X-Bridge-Token)
    │  POST /internal/originate (platform → bridge)
    ▼
aura_platform (FastAPI :8000)
    ├── PostgreSQL  (agents, sessions, leads, documents)
    ├── Celery      (index PDFs/TXT → Pinecone)
    └── Pinecone    (namespace agent-{id} per agent)
    ▲
aura_frontend (:80) — admin UI
```

Only **bridge** subscribes to ARI app `gemini-agent`. Platform does not start ARI/RTP.

---

## Prerequisites

| Item | Required | Get it |
| ---- | -------- | ------ |
| Docker + Compose | Yes | https://docs.docker.com/get-docker/ |
| Gemini API key | Yes | https://aistudio.google.com/apikey |
| Pinecone API key | For RAG | https://app.pinecone.io/ → API Keys |
| Zoiper | Yes | https://www.zoiper.com/ |
| Same LAN as PC | Yes | Phone on Wi‑Fi, not mobile data |

---

## Quick start

```bash
cp .env.example .env
# Edit .env: GEMINI_API_KEY, PINECONE_API_KEY

./start.sh up -d --build
./scripts/check.sh
```

First login: **http://localhost** → redirects to admin (login if needed) — `admin@aura.ai` / `changeme123`

Re-seed (idempotent): `make bootstrap`

---

## Environment variables

Single root **`.env`** for platform, celery, and bridge.

| Variable | Purpose |
| -------- | ------- |
| GEMINI_API_KEY | Gemini Live + embeddings + summaries |
| GEMINI_TEXT_MODEL | Post-call summaries/outputs (default `gemini-2.5-flash`) |
| PINECONE_API_KEY | RAG vector DB — https://app.pinecone.io/ |
| PINECONE_INDEX_NAME | Default `aura-knowledge` (auto-created) |
| PINECONE_ENVIRONMENT | Default `us-east-1` |
| BRIDGE_INTERNAL_TOKEN | Bridge ↔ platform secret |
| BRIDGE_URL | Platform → bridge HTTP (`http://bridge:8000` in Docker) |
| OUTBOUND_LAB_ENDPOINT | Default outbound dial target (`PJSIP/1001`) |
| OUTBOUND_DEFAULT_CALLER_ID | Caller ID for lab outbound (`1000`) |
| JWT_SECRET_KEY | Admin JWT |
| ADMIN_EMAIL / ADMIN_PASSWORD | Bootstrap admin |
| ARI_* | Must match asterisk/ari.conf |
| RTP_PORT | 40000 (ExternalMedia → bridge) |

LAN IP is auto-detected into **`.host.env`** on each **`./start.sh`** (set `EXTERNAL_IP=auto` in `.env`, or a fixed IP to override). If your router assigns a new IP, run **`./scripts/refresh-ip.sh`** and update Zoiper’s SIP server.

| `.env` variable | Purpose |
| --------------- | ------- |
| `EXTERNAL_IP` | `auto` (default) or fixed IPv4 e.g. `172.17.1.130` |
| `SIP_PORT` | SIP UDP port (default `5060`) |
| `SIP_USER` / `SIP_PASS` | Extension 1000 credentials |
| `SIP_USER_1001` / `SIP_PASS_1001` | Extension 1001 credentials |
| `SIP_CODEC` | `PCMU` (G.711 μ-law) recommended |

---

## Zoiper / SIP setup (call from your phone)

Use values from **Admin → Dashboard** or `./scripts/check.sh` (not `127.0.0.1` unless Zoiper runs on the same PC).

| Field | Value |
| ----- | ----- |
| Username | `1000` (or `SIP_USER` in `.env`) |
| Password | `1000pass` (or `SIP_PASS` in `.env`) |
| Domain / Server | Auto-detected LAN IP (e.g. `172.17.1.130`) |
| Port | `5060` UDP |
| Codecs | G.711 μ-law (PCMU) only |

Tips: use headphones; disable Zoiper echo cancellation for AI calls; dial 600 for echo test first.

---

## What to dial

| Ext | Agent | Purpose |
| --- | ----- | ------- |
| 701 | Maya — Lead Qualifier | Collect lead info, save via CRM |
| 702 | Aria — Trangotech Sales | Sales + pricing from KB |
| 703 | Sam — Support FAQ | FAQ from KB only |
| 704 | Riley — Cold Outbound | Inbound test of outbound agent persona |
| 700 | First active agent | Legacy fallback |
| 600 | Echo test | Mic/speaker check |

---

## Outbound calls (lab + CRM)

**Phase 2a** — full outbound CRM on lab SIP. **Phase 2b** — flip `OUTBOUND_MODE=trunk` when SIP provider + DID arrive (no CRM rewrite).

### Flow

```
Admin → Outbound / Campaigns
    → POST /api/outbound/dial (or /dial/batch, /campaigns/{id}/dial)
    → gemini_bridge (multi-call, per-call RTP port)
    → Asterisk → PJSIP/1001, 1002, …
    → Stasis → Gemini Live (Riley)
```

### Lab setup (single or dual phone)

1. Register softphones on same Wi‑Fi (`EXTERNAL_IP`):
   - **1001** / **1002** — prospect phones (`SIP_PASS_1001`, `SIP_PASS_1002`)
2. **Outbound Calls** → Riley → **Dial now** (one phone) or **Dial 1001 + 1002** (simultaneous)
3. **Campaigns** → create lab campaign with `PJSIP/1001` + `PJSIP/1002` → **Dial all**
4. Optional: **Leads** → **Call** (CRM context + DNC / call-window checks)
5. Review **Sessions** — OUTBOUND badge, `call_disposition`, leads

### Trunk mode (when ready)

```env
OUTBOUND_MODE=trunk
OUTBOUND_TRUNK_NAME=your_trunk   # Asterisk PJSIP trunk name
OUTBOUND_TRUNK_CALLER_ID=+15551234567
```

Configure trunk peer in `asterisk/pjsip.conf` — leads dial as `PJSIP/+E164@your_trunk`.

### Env vars

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `OUTBOUND_MODE` | `lab` | `lab` or `trunk` |
| `BRIDGE_URL` | `http://bridge:8000` | Platform → bridge |
| `OUTBOUND_LAB_ENDPOINT` | `PJSIP/1001` | Default lab target |
| `MAX_CONCURRENT_CALLS` | `5` | Bridge simultaneous calls |
| `RTP_PORT_BASE` / `COUNT` | `40000` / `50` | Per-call RTP ports |
| `OUTBOUND_CALL_*` | 9–18 UTC | Call window; disable with `OUTBOUND_CALL_WINDOW_ENABLED=false` |

### API

```bash
# Single dial
curl -X POST http://localhost:8000/api/outbound/dial \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id": 4, "endpoint": "PJSIP/1001"}'

# Batch (two phones)
curl -X POST http://localhost:8000/api/outbound/dial/batch \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id": 4, "endpoints": ["PJSIP/1001", "PJSIP/1002"]}'
```

AMD and large-scale dialer queues are **Phase 2c+**.

---

## Admin UI walkthrough

| Page | Purpose |
| ---- | ------- |
| Dashboard | Getting started + SIP IP |
| Agents | Extensions, prompts, tools (inbound + outbound_sales) |
| Outbound Calls | Dial / batch dial (1001+1002) |
| Campaigns | Batch campaigns, parallel lab demo |
| Documents | Upload KB files per agent |
| Sessions | Transcripts + auto summaries (inbound + outbound) |
| Leads | CRM from calls and agent tools |

API: http://localhost:8000/health  
SIP info: http://localhost:8000/api/system/info

---

## How to create an agent

1. Admin → **Agents** → **New Agent**
2. Set name, **inbound extension** (e.g. 704), voice, model, system prompt, tools
3. Enable **search_knowledge_base** if using RAG
4. Add dialplan in `asterisk/extensions.conf`:

```ini
exten => 704,1,Stasis(gemini-agent,my-slug)
 same => n,Hangup()
```

5. `./start.sh up -d asterisk`
6. Upload docs in **Documents** for that agent
7. Dial extension from Zoiper

Human-like voice behavior is added automatically (master prompt).

---

## AI knowledge base (RAG)

**Flow:** Upload doc → Celery chunks text → Gemini embeddings → Pinecone `agent-{id}` namespace → `search_knowledge_base` tool during calls.

**Seed docs** (auto on bootstrap if PINECONE_API_KEY set):

| File | Agent | Ext |
| ---- | ----- | --- |
| lead-qualification-script.txt | Maya | 701 |
| trangotech-services.txt | Aria | 702 |
| support-faq.txt | Sam | 703 |
| cold-outbound-script.txt | Riley | 704 (outbound) |

**Pinecone:** Index `aura-knowledge` is auto-created. Bootstrap is idempotent (no duplicate agents/docs).

**Get Pinecone key:** https://app.pinecone.io/ → API Keys → Create → paste in `.env` → `make bootstrap`

---

## Project structure

```
astrersik/
├── .env / .env.example / .host.env
├── docker-compose.yml
├── start.sh
├── Makefile
├── scripts/check.sh
├── asterisk/          # SIP, ARI, extensions 701-704
├── bridge/app/main.py # Telephony + Gemini + originate + platform client
└── eplanet-calling-agent/gemini-sales-agent/
    ├── backend/       # API, RAG, bootstrap, seed_data/
    └── frontend/      # React admin
```

---

## Useful commands

```bash
./start.sh up -d --build
./scripts/check.sh
make bootstrap
make logs
docker logs -f aura_celery
```

---

## Verification checklist

| Step | Check |
| ---- | ----- |
| check.sh | All OK |
| Login | admin@aura.ai / changeme123 |
| Agents | 701–704 (Riley = outbound) |
| Documents | 4 seed docs **indexed** |
| Zoiper | Registered to EXTERNAL_IP |
| Dial 701 | Lead in Leads page |
| Outbound | Admin → Outbound → dial 1001, answer on 1001 Zoiper |
| Sessions | Transcript + summary + disposition (outbound) |

---

## Troubleshooting

- **No register:** same Wi‑Fi, check EXTERNAL_IP, port 5060 free
- **No audio:** dial 600, headphones, APM_ENABLED=0
- **Call drops at ~32s:** Asterisk Contact header / NAT — see `asterisk/pjsip.conf.template` local_net fix
- **Empty summary/outputs:** check `GEMINI_API_KEY` and `GEMINI_TEXT_MODEL`; open Session Detail → **Generate all**
- **Empty Notes page:** default tab is **all**; session notes auto-save after each call
- **RAG failed:** check PINECONE_API_KEY, `docker logs aura_celery`, `make bootstrap`
- **One call only:** hang up before redialing

---

## Roadmap (not yet implemented)

Browser voice UI, PSTN/SIP trunk for real numbers, outbound campaigns/dialer, answering-machine detection, multi-concurrent bridge calls.
