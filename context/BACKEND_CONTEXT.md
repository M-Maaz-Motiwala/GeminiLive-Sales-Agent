Generated From: Current Repository State
Last Reviewed: 2026-07-01
Source of Truth: Code
Intended Audience: AI Coding Assistants & Developers
Estimated Reading Time: 10-15 minutes

# Overview

The backend is the Aura platform API: a FastAPI application under `eplanet-calling-agent/gemini-sales-agent/backend`. It owns persistent business state, authentication, CRM workflows, agent configuration, RAG document orchestration, outbound dialing policy, generated DID dialplan sync, and the internal contract consumed by the telephony bridge.

It is not the realtime voice/media service. SIP, ARI websocket handling, ExternalMedia RTP, and Gemini Live streaming are owned by `bridge/app/main.py`.

# Responsibilities

The backend owns:

- REST API under `/api/*`.
- Internal bridge API under `/internal/*`.
- SQLAlchemy async database access.
- User auth, Google auth, role checks, and approval flow.
- Organization/DID/agent configuration.
- Session, message, tool-call, output, lead, contact, note, campaign, DNC, and document persistence.
- Gemini Live config construction for the bridge.
- Gemini tool dispatch and tool-call persistence.
- RAG document indexing orchestration through Celery and Pinecone.
- Google Calendar OAuth token storage and calendar tools.
- Generated organization DID dialplan file creation and best-effort Asterisk reload.

The backend does not own:

- SIP registration.
- Dialplan execution.
- ARI app subscription.
- RTP packet parsing or audio conversion.
- Gemini Live websocket streaming.
- Frontend rendering or navigation.

# Important Files

- `backend/main.py`: FastAPI app factory, CORS, lifespan startup, and router inclusion.
- `backend/config.py`: central `Settings` object for Gemini, DB, Redis, JWT, Pinecone, ARI, bridge, outbound, Asterisk generated dir, and Google OAuth.
- `backend/db/database.py`: async SQLAlchemy engine/session dependency and startup DB initialization.
- `backend/db/models.py`: canonical domain schema and relationships.
- `backend/db/migrate.py` plus `backend/alembic/versions/*`: schema evolution. Startup also runs code-level migrations.
- `backend/auth/router.py`: local JWT login/refresh/me and Google OAuth login callback.
- `backend/auth/deps.py`: bearer-token dependencies and role guards.
- `backend/routers/internal_bridge.py`: call lifecycle API used only by bridge.
- `backend/routers/outbound.py`: authenticated outbound dial/status/hangup APIs.
- `backend/routers/campaigns.py`: campaign and campaign-lead orchestration.
- `backend/routers/agents.py`: agent CRUD, slug creation, extension allocation, tool/model/prompt fields.
- `backend/routers/organizations.py`: organization CRUD and DID dialplan sync.
- `backend/routers/documents.py`: file upload, retry, delete, and queueing indexing tasks.
- `backend/routers/calendar.py`: Google Calendar OAuth and availability endpoints.
- `backend/services/live_config.py`: converts `Agent` rows plus KB/lead/callback context into Gemini Live config.
- `backend/services/tool_executor.py`: Gemini function declarations, enabled-tool filtering, dispatch, and tool-call audit.
- `backend/services/rag_service.py`: Pinecone index, embeddings, namespaces, query, and delete.
- `backend/services/document_indexer.py`: Celery task for extraction/chunk/embed/upsert.
- `backend/services/outbound_dialer.py`: shared dial validation and bridge originate call.
- `backend/services/bridge_client.py`: HTTP client for bridge internal APIs.
- `backend/services/callback_router.py`: inbound agent selection by DID, callback ownership, and busy-agent checks.
- `backend/services/asterisk_registry.py`: writes generated `org-dids.conf` and reloads Asterisk.
- `backend/scripts/bootstrap.py`: one-shot migration/admin/org/agent/RAG seed bootstrap.

# Runtime Flow

## Startup

`backend/main.py` creates the FastAPI app with a lifespan handler. On startup it calls `init_db()`, which:

1. Creates tables from SQLAlchemy metadata.
2. Applies code-level migrations.

In Docker, `platform_init` separately runs `python -m backend.scripts.bootstrap` after platform health. Bootstrap is idempotent and creates the admin user, default organization, seed agents, optional Pinecone index, and optional seed RAG documents.

## Request Lifecycle

Frontend/API caller -> FastAPI router -> dependencies (`get_db`, `get_current_user` or role guard) -> service logic or direct SQLAlchemy operations -> `get_db` commits on success or rolls back on exception -> JSON response.

The codebase uses a pragmatic router/service split rather than a formal repository layer. Many CRUD routes talk directly to SQLAlchemy; shared domain behavior lives under `backend/services`.

## Auth

Local auth:

`POST /api/auth/login` verifies user/password and returns access/refresh JWTs. `GET /api/auth/me` resolves the current user from bearer token. Refresh tokens are checked by token type.

Google auth:

`GET /api/auth/google` redirects to Google. Callback exchanges the code for tokens, fetches userinfo, links an existing local user by email or creates an unapproved Google user, then redirects to frontend with JWTs.

Approval:

The auth dependency only requires an active valid user. The frontend enforces approval routing. Backend has role guard helpers (`require_admin`, `require_org_head_or_admin`, `require_approved_user`), but not every router uses stricter guards.

## Internal Bridge Call Start

`POST /internal/calls/start` is the backend's call-entry contract.

Flow:

Bridge payload -> verify `X-Bridge-Token` -> resolve agent -> build session metadata -> build contact/lead/callback context -> create active `Session` -> preload KB chunks -> call `agent_to_live_config()` -> return Gemini Live config with `session_id`.

Inbound resolution:

- Explicit `agent_slug` wins if active.
- Dedicated 705-799 extension routes by `Agent.inbound_extension`.
- Fleet extensions 700-704 use default DID and callback-aware sales pool routing.
- DID calls route to active sales/outbound agents whose DID matches the organization DID.

Outbound resolution:

- Bridge passes explicit `agent_slug`.
- Backend loads matching active agent.
- Lead/campaign metadata is attached when present.

## Internal Bridge Runtime

- `/internal/calls/transcript`: persists user/model transcript messages.
- `/internal/calls/tool`: dispatches Gemini function calls through `tool_executor`.
- `/internal/calls/dial-status`: merges live dial status into session metadata.
- `/internal/calls/end`: marks session ended, stores bridge stats/token usage, finalizes metrics, commits, then launches async post-call processing.

## Outbound Dial

Authenticated caller -> `/api/outbound/dial` -> load active agent and optional lead -> `dial_one()` -> DNC/call-window validation -> endpoint/caller ID resolution -> bridge capacity check -> bridge `/internal/originate` -> response returns dialing state.

Batch and campaign flows reuse the same `dial_one()` behavior. The backend is the policy gate; frontend should not call bridge originate directly.

## Document Indexing

`POST /api/documents` writes the uploaded file to the `uploads` volume, creates a `Document` row, and queues `index_document.delay(...)`.

Celery task:

File -> text extraction (PDF/DOCX/text) -> word chunks -> Gemini embeddings -> Pinecone upsert -> update `Document.status`, `chunk_count`, `indexed_at`, or retry/fail metadata.

## Tool Dispatch

The bridge forwards Gemini function calls to `/internal/calls/tool`. `tool_executor.dispatch()`:

- Handles CRM tools such as lead creation/update, contact search, notes, status updates.
- Handles `search_knowledge_base` through RAG tools.
- Handles calendar tools by resolving session owner.
- Handles `end_call` by returning an ending signal to the bridge.
- Persists each tool call to `tool_calls`.

# Data Flow

Call-start data flow:

```
Bridge Stasis event
-> /internal/calls/start
-> callback_router / session_contact / live_config
-> PostgreSQL Session row
-> Pinecone optional KB preload
-> Gemini Live config returned to Bridge
```

Tool-call data flow:

```
Gemini Live function call
-> Bridge
-> /internal/calls/tool
-> tool_executor
-> CRM/RAG/Calendar service
-> ToolCall row
-> FunctionResponse
-> Bridge
-> Gemini Live
```

RAG data flow:

```
Document upload
-> Document row + uploads volume
-> Redis/Celery task
-> text extraction/chunking
-> Gemini embedding API
-> Pinecone namespace org-{id} or agent-{id}
-> call preload or search_knowledge_base
```

Outbound data flow:

```
Frontend
-> /api/outbound/dial
-> outbound_dialer policy + endpoint resolver
-> bridge_client.originate_outbound
-> Bridge /internal/originate
-> Asterisk ARI originate
-> /internal/calls/start on StasisStart
```

# Dependencies

Internal:

- `routers` depend on `db`, `auth`, and domain services.
- `internal_bridge` depends on callback routing, live config, tool execution, post-call, session metrics.
- `outbound` depends on bridge client, dialer, policy, status enrichment.
- `documents` depends on Celery document indexer.
- `organizations` depends on Asterisk registry.

External:

- PostgreSQL via asyncpg.
- Redis as Celery broker/backend.
- Pinecone for vector storage.
- Google Gemini API for Live config models, embeddings, and text processing.
- Google OAuth and Calendar APIs.
- Bridge service over HTTP with `X-Bridge-Token`.
- Docker CLI/socket for best-effort Asterisk dialplan reload.

# Configuration

Important settings from `backend/config.py`:

- `database_url`: async SQLAlchemy PostgreSQL URL.
- `redis_url`: Celery broker/backend.
- `jwt_secret_key`, `jwt_algorithm`, token expiry settings.
- `gemini_api_key`, `gemini_text_model`.
- `pinecone_api_key`, `pinecone_environment`, `pinecone_index_name`.
- `bridge_internal_token`: required for internal bridge endpoints.
- `bridge_url`: platform-to-bridge base URL.
- `outbound_mode`, `outbound_lab_endpoint`, `outbound_default_caller_id`, `outbound_default_country_code`, trunk settings.
- `asterisk_generated_dir`, `asterisk_container_name`.
- outbound call-window settings.
- Google OAuth and Calendar redirect/encryption settings.

# Design Decisions

- The backend builds complete Gemini Live configuration at call start instead of letting the bridge read the database. This keeps persistence/business logic centralized.
- Tool execution happens in the backend because tools mutate CRM/RAG/calendar state and need DB access.
- Outbound call policy is enforced before bridge originate, so the bridge stays a media/origination service rather than a CRM policy engine.
- Agent-specific and organization-level documents use different Pinecone namespaces. Queries include org and agent namespaces and intentionally avoid global fallback for org agents.
- Organization DID updates propagate to agents and generated dialplan, making organization DID the source of truth for tenant telephony identity.
- Celery disposes inherited DB pools after worker fork and after tasks to avoid asyncpg event-loop reuse issues.

# Critical Files

- `backend/db/models.py`: schema relationships and enums drive almost every service.
- `backend/routers/internal_bridge.py`: bridge contract; breaking fields affects live calls.
- `backend/services/live_config.py`: prompt/tool/context assembly; mistakes affect every AI call.
- `backend/services/tool_executor.py`: single source for Gemini tool declarations and dispatch.
- `backend/services/rag_service.py`: tenant isolation and Pinecone behavior.
- `backend/services/outbound_dialer.py`: capacity, policy, endpoint, and caller ID rules.
- `backend/services/callback_router.py`: inbound routing and callback ownership.
- `backend/services/asterisk_registry.py`: generated DID dialplan and reload behavior.
- `backend/config.py`: env names consumed by Docker/bridge/scripts.

# Common Debugging

- API 401: inspect bearer token in frontend localStorage, JWT secret, `/api/auth/me`.
- New Google user stuck: check `is_approved`, `organization_id`, `designation`, and access request status.
- DB changes missing: check `init_db()`, `backend/db/migrate.py`, alembic files, and platform logs.
- Internal bridge 403: `BRIDGE_INTERNAL_TOKEN` mismatch between platform and bridge.
- No session rows for calls: bridge may not reach `/internal/calls/start`; inspect bridge logs and platform URL.
- Tool calls fail: check `enabled_tools` on agent, `TOOL_DECLARATIONS`, dispatch branch, and service handler errors.
- RAG empty: verify document status indexed, Pinecone key/index, namespace, and `search_knowledge_base` enabled.
- Outbound 409: bridge or platform concurrent-call limit reached.
- Outbound no endpoint: inspect endpoint resolver and lead phone normalization.
- DID route not updated: check `asterisk/generated_<env>/org-dids.conf`, Docker socket availability, and Asterisk dialplan reload.

# AI Guidance

Where to add code:

- New REST area: create a router under `backend/routers`, include it in `backend/main.py`, and keep shared logic under `backend/services`.
- New persistent entity: update `backend/db/models.py` and add an idempotent migration path.
- New Gemini tool: add declaration and dispatch branch in `tool_executor.py`; put domain logic in `backend/services/tools`.
- New call context: extend `internal_bridge.CallStartIn`, metadata construction, and `live_config.agent_to_live_config()`.
- New outbound behavior: prefer `outbound_dialer.py`, `outbound_policy.py`, `endpoint_resolver.py`, and `bridge_client.py`.
- New RAG behavior: preserve namespace isolation in `rag_service.py`.

Patterns:

- Use `get_db` for request-scoped async sessions; it commits after the route returns.
- Use service modules when behavior is reused by multiple routers or touches external systems.
- Keep bridge-facing responses JSON-serializable.
- Treat `Session.meta` as the flexible integration surface for dial status, contact context, metrics, and bridge stats.
- Use `Agent.enabled_tools` to expose model tools; do not send all tools by default except `end_call`.

Avoid:

- Adding bridge/media dependencies to backend.
- Letting browser routes call `/internal/*`.
- Persisting secrets unencrypted when code already has an encrypted token model.
- Falling back from tenant namespaces to global RAG.
- Duplicating tool declarations in frontend or bridge.
- Manually editing generated Asterisk DID files.
