# Aura Intelligence Platform

Full-stack AI voice agent platform with Gemini Live, Asterisk VoIP bridging, Pinecone RAG, admin UX, CRM tooling, and async document indexing.

## Overview

This repository contains a complete production-ready architecture for an AI-powered conversational platform.

- **Backend:** FastAPI + async SQLAlchemy + PostgreSQL + Celery + Redis
- **Voice integration:** Gemini Live + Asterisk ARI + RTP bridge
- **Knowledge:** Pinecone embeddings + RAG search + document indexing
- **Admin UX:** React + Vite + JWT auth + CRUD for agents, sessions, leads, contacts, documents, outputs, notes
- **Deployment:** Docker Compose with `postgres`, `redis`, `fastapi`, `celery_worker`, `asterisk`, and `frontend`

## Architecture

### Flow

1. Browser connects to `/ws/live` via WebSocket.
2. Browser microphone audio is captured and streamed to FastAPI.
3. FastAPI forwards audio to Gemini Live via `GeminiLiveSession`.
4. Gemini returns audio + transcripts and triggers tool calls when needed.
5. Tool calls are executed by backend handlers and logged to PostgreSQL.
6. Admin UI manages agents, sessions, CRM data, documents, and outputs.
7. Asterisk can also receive SIP calls and bridge them to Gemini using ExternalMedia + RTP.

### Services

- `frontend`: React app for user voice session and admin dashboard
- `backend`: FastAPI service with API routers, websocket session proxy, and Gemini integration
- `asterisk`: Asterisk PBX container for SIP/VoIP call handling
- `postgres`: Persistent relational storage
- `redis`: Backend broker for Celery async tasks
- `celery_worker`: Document indexing worker and background task executor

## Folder Structure

```
gemini-sales-agent/
├── asterisk/                    # Asterisk Docker container and config
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── etc/asterisk/            # pjsip.conf, extensions.conf, ari.conf, http.conf, rtp.conf
├── backend/                     # FastAPI backend service
│   ├── auth/                    # JWT auth router, dependencies, helpers
│   ├── db/                      # SQLAlchemy models + async DB engine
│   ├── routers/                 # REST and WebSocket API routes
│   ├── scripts/                 # setup scripts (admin seed)
│   ├── services/                # Gemini Live, tool executor, Asterisk/RTP bridge, RAG, summarizer
│   ├── requirements.txt         # backend Python dependencies
│   └── Dockerfile               # backend container
├── frontend/                    # React + Vite frontend
│   ├── src/
│   │   ├── auth/                # auth context
│   │   ├── components/          # UI wrapper + protected route
│   │   ├── hooks/               # useGeminiLive WebSocket hook
│   │   ├── pages/admin/         # admin interface pages
│   │   └── App.tsx              # main app router
│   ├── Dockerfile
│   └── nginx.conf               # SPA + API proxy config
├── docker-compose.yml           # full local stack
├── .env.example                 # template environment variables
└── README.md                    # this file
```

## Key Backend Capabilities

- API auth with JWT and refresh tokens
- Agent CRUD and persona management
- Session tracking with transcripts, summaries, tool calls, and outputs
- CRM entities: leads, contacts, notes
- Document upload, async indexing, and Pinecone RAG search
- Gemini Live voice session proxy with tool calling
- Asterisk ARI voice bridge for SIP calls
- RTP bridging and codec conversion for realtime audio

## Key Frontend Capabilities

- Public voice UI with live transcript and audio visualizer
- Admin dashboard for:
  - agents and tools
  - session history and summaries
  - leads / contacts management
  - document upload and indexing status
  - outputs and notes review
- JWT-based protected admin route
- WebSocket voice transport through FastAPI backend

## Required Environment Variables

Copy `.env.example` to `.env` and fill in the values.

Important values:

- `GEMINI_API_KEY` — Gemini API key
- `PINECONE_API_KEY` — Pinecone API key
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis URL
- `JWT_SECRET_KEY` — backend auth secret
- `ASTERISK_HOST`, `ASTERISK_PORT`, `ASTERISK_USER`, `ASTERISK_PASSWORD` — ARI connection settings for your Asterisk server
- `SIP_HOST`, `SIP_PORT`, `SIP_USER`, `SIP_PASS` — external SIP trunk credentials (optional)
- `VITE_API_URL` — frontend API base URL

> Do not commit `.env` to source control.

### Connect your own Asterisk server

This system supports your own Asterisk installation in two modes:

1. **Using the included Docker Asterisk service**
   - Set `ASTERISK_HOST=asterisk` in `.env` when running with `docker compose`
   - The backend will connect to the local container's ARI endpoint
   - SIP phones or trunks can register to the container via port `5060`

2. **Using an external/self-hosted Asterisk server**
   - Set `ASTERISK_HOST` to your Asterisk machine IP or hostname
   - Set `ASTERISK_PORT=8088`, `ASTERISK_USER`, `ASTERISK_PASSWORD` to your ARI credentials
   - Ensure the backend service can reach that host from Docker
   - If running Asterisk outside Docker on Linux, use the machine IP or Docker host networking

If you do not want an external SIP trunk, leave `SIP_HOST` / `SIP_USER` / `SIP_PASS` unset and use only local Asterisk extensions.

## How to Run Locally

### Prerequisites

- Docker
- Docker Compose
- Node.js / npm (for local frontend work, if not using Docker)

### Start the stack

```bash
cd /home/shahbaz/Downloads/gemini-sales-agent
docker compose up --build
```

This brings up:

- `postgres` on default container network
- `redis` for task queue
- `fastapi` backend on port `8000`
- `frontend` UI on port `80`
- `asterisk` SIP / ARI service
- `celery_worker` for async indexing

### Seed the first admin user

```bash
docker compose exec fastapi python -m backend.scripts.create_admin
```

### Access the app

- User / voice app: `http://localhost`
- Admin dashboard: `http://localhost/admin`
- FastAPI docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## Testing Asterisk with a softphone

You can test inbound calls without a phone number by registering a softphone to the local Asterisk server.

1. Install a softphone app such as Zoiper, Linphone, or MicroSIP.
2. Configure a SIP account using the local Asterisk extension:
   - SIP username: `6001`
   - SIP password: `aura6001`
   - SIP server / domain: `localhost`
   - SIP port: `5060`
   - Transport: UDP
3. In Asterisk config, extension `6001` is defined in `asterisk/etc/asterisk/pjsip.conf` and uses context `from-internal`.
4. Make a test call by dialing extension `1000` from the softphone. This route is defined in `asterisk/etc/asterisk/extensions.conf` and sends the call into the Gemini AI Stasis app.
5. If the app is running, the call should be answered and bridged into the AI session.

If you are running Asterisk outside Docker or on a remote machine, set `ASTERISK_HOST` to the Asterisk host IP in `.env`, and use that host address as the softphone server.

If you want to test completely without an external number, you can also call between two softphones registered to Asterisk, or use the local extension dialplan.

## Development Workflow

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Running TypeScript check

```bash
cd frontend
npx tsc --noEmit
```

## Notes and Best Practices

- The browser voice client now connects through the backend WebSocket at `/ws/live` instead of directly to Gemini.
- Asterisk uses ExternalMedia + RTP bridge so SIP call audio can flow into Gemini and back.
- Pinecone is used for RAG-based knowledge search and document embeddings.
- All generated session state is persisted to PostgreSQL for reporting and admin review.

## Troubleshooting

- If the frontend cannot connect, verify `VITE_API_URL` and CORS configuration.
- If Asterisk cannot register to the trunk, check `pjsip.conf` and external SIP credentials.
- If Gemini sessions fail, confirm `GEMINI_API_KEY` and the model config.

## Security Reminder

- Rotate any API keys shared in this repository.
- Keep `.env` secret.
- Use strong JWT secrets and database passwords in production.
