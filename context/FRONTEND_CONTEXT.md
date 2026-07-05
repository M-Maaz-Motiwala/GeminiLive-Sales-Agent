Generated From: Current Repository State
Last Reviewed: 2026-07-01
Source of Truth: Code
Intended Audience: AI Coding Assistants & Developers
Estimated Reading Time: 10-15 minutes

# Overview

The frontend is a React 19 + Vite admin SPA under `eplanet-calling-agent/gemini-sales-agent/frontend`. It is the operational UI for the AI calling platform: users log in, manage organizations and agents, inspect call sessions, run outbound calls and campaigns, manage CRM records, upload knowledge documents, review outputs/notes, handle access requests, and configure settings.

In Docker it is built into static assets and served by nginx. Nginx proxies `/api/` and `/ws/` to the platform backend, so production-style frontend calls are same-origin by default.

# Responsibilities

The frontend owns:

- Browser routing and layout.
- Authentication token storage and redirect behavior.
- Role-aware navigation.
- Admin workflows and forms.
- REST calls to backend `/api/*`.
- Display of session, outbound, campaign, CRM, document, settings, and help/docs UI.

The frontend does not own:

- Database writes except via backend APIs.
- Authentication verification beyond token presence and `/api/auth/me`.
- Telephony originate directly; outbound calls go through backend policy endpoints.
- Bridge or Asterisk internal APIs.
- RAG indexing; it uploads documents and observes status.

# Important Files

- `src/App.tsx`: route graph and protected/admin nesting.
- `src/auth/AuthContext.tsx`: JWT/localStorage state, login, Google login redirect, `/api/auth/me` validation, logout, user refresh.
- `src/components/ProtectedRoute.tsx`: authentication and approval/access-request routing.
- `src/components/admin/AdminLayout.tsx`: persistent admin shell, role-aware navigation, access request badge, logout.
- `src/lib/api.ts`: common `apiFetch`, API base selection, bearer token injection, 401 handling, FormData handling.
- `src/lib/outbound.ts`, `src/lib/campaigns.ts`: domain API helpers for outbound/campaign pages.
- `src/pages/admin/*.tsx`: admin pages mapped directly from routes.
- `src/pages/GoogleCallback.tsx`: captures JWT query params after Google OAuth.
- `src/pages/AccessRequestForm.tsx`, `src/pages/PendingApproval.tsx`: unapproved-user workflow.
- `frontend/nginx.conf`: static serving, SPA fallback, `/api` and `/ws` proxy to platform.
- `frontend/package.json`: React/Vite/Tailwind/lucide/mermaid dependencies and scripts.

# Runtime Flow

## App Startup

Browser loads nginx-served static app -> `main.tsx` renders `App` -> `AuthProvider` loads token/user from localStorage -> validates token by calling `/api/auth/me` -> `BrowserRouter` renders route tree.

## Login

Local login:

Login form -> `AuthContext.login()` -> `POST /api/auth/login` -> `GET /api/auth/me` -> store `aura_token` and `aura_user` in localStorage -> routes render.

Google login:

Login button -> browser navigates to `${API_BASE}/api/auth/google` -> backend/Google OAuth -> frontend `/auth/google/callback` captures tokens -> user state updates.

## Protected Routing

`ProtectedRoute` checks:

- No token: redirect to `/admin/login`.
- Authenticated but unapproved:
  - Missing organization/designation: redirect to `/access-request-form`.
  - Has submitted info: redirect to `/pending-approval`.
- Approved: render requested children.

The route guard does not enforce role permissions by itself. Role-aware visibility is mainly in `AdminLayout` navigation; backend should still enforce authorization for sensitive operations.

## Admin Navigation

`AdminLayout` renders the left navigation based on `user.role`:

- `admin`: all major pages including Organizations and Access Requests.
- `org_head`: operational pages and Access Requests, not Organizations.
- `user`: command center, sessions, outbound, campaigns, CRM, outputs, notes, settings.

It periodically reacts to `accessRequestsChanged` events to refresh access request count.

# Data Flow

Typical page data flow:

```
React page/component
-> useAuth() for token/user
-> apiFetch('/api/...', token)
-> nginx /api proxy
-> FastAPI backend
-> PostgreSQL/external service
-> JSON response
-> page state
```

Auth data flow:

```
Login/OAuth callback
-> backend JWT
-> localStorage aura_token
-> AuthContext token state
-> apiFetch Authorization header
```

Outbound flow from UI:

```
Outbound/Campaign page
-> /api/outbound/dial or /api/campaigns
-> backend policy + bridge originate
-> poll /api/outbound/status or dial-status
-> render live phase/outcome
```

Document flow from UI:

```
Documents page
-> multipart upload /api/documents
-> backend creates Document + queues Celery
-> page lists status pending/indexing/indexed/failed
```

# Dependencies

Frontend libraries:

- React 19.
- React Router.
- Vite.
- Tailwind CSS stack.
- lucide-react for icons.
- Mermaid for docs diagrams.
- motion, base-ui/shadcn-related UI packages.

Runtime services:

- Backend platform through same-origin `/api`.
- Backend websocket through same-origin `/ws` where used.
- Google OAuth is initiated by backend URL, not direct frontend SDK.

# Configuration

API base:

- `src/lib/api.ts` uses `import.meta.env.VITE_API_URL ?? ''`.
- `AdminLayout.tsx` currently uses `import.meta.env.VITE_API_BASE || 'http://localhost:8000'` for access request count. This is a separate env name from `VITE_API_URL`; treat that inconsistency carefully if changing deployment config.
- In Docker/nginx, same-origin `/api` is expected to work because nginx proxies to `platform:8000`.

Build/serve:

- Dev: `npm run dev` runs Vite on port 3000.
- Build: `npm run build`.
- Docker frontend serves built static files through nginx on container port 80.

# Design Decisions

- The frontend is an admin application, not a public landing page.
- Auth state is lightweight and stored in localStorage; backend remains the source of truth through `/api/auth/me`.
- Same-origin API calls avoid CORS/runtime host coupling in Docker.
- Role filtering is done in the navigation for UX, but backend routes still need server-side guardrails for actual authorization.
- UI pages are domain-oriented rather than deeply abstracted: Agents, Sessions, Leads, Outbound, Campaigns, Documents, etc.

# Critical Files

- `src/App.tsx`: route additions/removals affect the whole app.
- `src/auth/AuthContext.tsx`: token lifecycle, unauthorized handler, Google login.
- `src/lib/api.ts`: all common API error and auth behavior.
- `src/components/ProtectedRoute.tsx`: approval gate.
- `src/components/admin/AdminLayout.tsx`: role visibility and navigation.
- `frontend/nginx.conf`: deployment pathing and API/websocket proxy.

# Common Debugging

- Blank or redirect loop: inspect localStorage `aura_token`/`aura_user`, `/api/auth/me`, and approval fields.
- 401 after login: token expired/invalid or `JWT_SECRET_KEY` changed; `apiFetch` calls unauthorized handler.
- API works locally but not in Docker: check nginx `/api/` proxy and frontend API env vars.
- Access request badge missing: `AdminLayout` uses `VITE_API_BASE`, not `VITE_API_URL`.
- User cannot access admin page: check `ProtectedRoute` approval logic and role-filtered nav.
- Upload fails: ensure request uses FormData so `apiFetch` does not force JSON content type.
- WebSocket fails: check nginx `/ws/` upgrade proxy and backend websocket route.

# AI Guidance

Where to add features:

- New admin page: add `src/pages/admin/NewPage.tsx`, route in `src/App.tsx`, and nav entry in `AdminLayout.tsx` if user-facing.
- New API helper: add to `src/lib/<domain>.ts` when shared by multiple components; otherwise use `apiFetch` directly in the page.
- New protected standalone route: wrap with `ProtectedRoute` in `App.tsx`.
- New docs/help UI: use existing `HelpDocs`, `DocsSection`, and `MermaidDiagram` patterns.

Patterns:

- Use `useAuth()` for token/user.
- Use `apiFetch` for authenticated JSON and FormData calls.
- Do not embed backend host URLs in page components unless env handling is aligned with nginx deployment.
- Use lucide icons in navigation/actions where available.
- Keep role-specific visibility consistent between nav and page-level behavior.

Avoid:

- Calling bridge `/internal/*` APIs from the browser.
- Duplicating auth token parsing in individual pages.
- Assuming nav role filtering is security.
- Adding a second API abstraction without a strong reason.
- Building frontend state as the source of truth for live calls; poll/read backend/bridge-derived status through backend endpoints.
