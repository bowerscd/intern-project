# vibe-coded-front-end

Flask + vanilla TypeScript frontend for the **Mealbot** and **Happy Hour** web applications.

No React, Angular, or jQuery — the UI is built with plain TypeScript compiled to ES modules and loaded directly by the browser.

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Welcome page with navigation links |
| `/login` | OIDC login/registration (Google, plus test provider in dev) |
| `/auth/callback` | Post-OIDC landing — validates session, redirects to account |
| `/auth/complete-registration` | New users pick a username after OIDC signup |
| `/auth/claim-account` | Claim a pre-existing legacy account |
| `/account` | Profile management and feature-access toggles (Mealbot, Happy Hour, Tyrant) |
| `/mealbot` | Dashboard — balance summary, record meals, global + personal ledger |
| `/mealbot/individualized` | Per-user debt breakdown and recent activity |
| `/happyhour` | Public view — upcoming event, rotation schedule, past events |

## Architecture

### Backend communication

The Flask app operates in one of three modes, controlled by environment variables:

| Mode | `USE_MOCK` | `USE_PROXY` | Behaviour |
|------|------------|-------------|-----------|
| **Mock** | `true` | — | All data served from client-side mock data. No backend needed. |
| **Proxy** | `false` | `true` | Flask reverse-proxies `/api/*` to the FastAPI backend. Session cookies flow naturally on the same origin. |
| **Direct** | `false` | `false` | Browser calls the backend directly. Login redirects are qualified with the frontend origin. |

### TypeScript layer

Source lives in `src/ts/`, compiled to `static/dist/` via `tsc`.

| Module | Purpose |
|--------|---------|
| `main.ts` | Entry point — maps URL paths to page render functions |
| `pages.ts` | All page renderers — DOM manipulation, form handling, infinite scroll |
| `types.ts` | Type definitions + `ClaimFlags` bitmask codec |
| `utils.ts` | DOM helpers — `esc()` (XSS escaping), `table()`, `formatDate()`, infinite scroll setup |
| `services/apiClient.ts` | Typed fetch client with `credentials: "include"` for all API calls |
| `services/dataProvider.ts` | Strategy-pattern facade — dynamically imports mock or live data based on `window.__USE_MOCK` |
| `services/mockData.ts` | Procedurally generated datasets (120 meal records, 80 events, 50 locations) |
| `services/liveData.ts` | Live data provider wrapping the API client |
| `generated/openapiClient.ts` | Auto-generated typed fetch functions from the backend's OpenAPI schema |

### Auth gating

A `@app.before_request` hook redirects unauthenticated users to `/login`.
Exempt paths: static files, `/api/*`, `/login`, `/auth/*`, `/healthz`.
In mock mode, gating is disabled entirely.

### Notable patterns

- **Mock-first development** — the full UI works with rich mock data, no backend required.
- **Infinite scroll** — large tables use `IntersectionObserver` with a sentinel element, loading 20 rows at a time.
- **XSS protection** — all dynamic content passes through `esc()` before `innerHTML` insertion.
- **Request ID tracing** — every request gets a `X-Request-ID` header propagated through both frontend and backend.
- **Responsive design** — slide-in sidebar nav on mobile (< 768px), 44px minimum tap targets.

## Configuration

Configuration is managed through `config.py` and `server.py` modules, which read environment variables with smart defaults.

Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SERVER_HOSTNAME` | OS hostname | Public hostname — used for session cookie name |
| `BACKEND_HOSTNAME` | `backend` | Internal Docker hostname for backend service |
| `BACKEND_PORT` | `80` | Backend service port |
| `PORT` | `80` | Port this service listens on |
| `USE_MOCK` | `false` | Enable mock data mode |
| `USE_PROXY` | `true` | Enable reverse proxy mode (`/api/*` → backend) |
| `DEV` | `false` | Dev mode — relaxed caching, verbose errors |

**Smart defaults:**
- `SESSION_COOKIE_NAME` auto-computed as `{SERVER_HOSTNAME}.session`
- Backend URL constructed from `BACKEND_HOSTNAME` and `BACKEND_PORT`
- `API_BASE` (client-side) automatically set based on proxy/mock mode
- `SERVER_HOSTNAME` defaults to `socket.gethostname()` if not set

**Legacy variables** (now ignored):
- `API_BASE` — use `BACKEND_HOSTNAME` and `BACKEND_PORT` instead
- `SESSION_COOKIE_NAME` — auto-computed from `SERVER_HOSTNAME`

## Development

```bash
# Install Python + Node dependencies
make install

# Compile TypeScript
make build

# Run Flask dev server (port 5001)
make dev

# Run all tests (Python + TypeScript)
make test-all

# Lint / format
make lint
make format

# Regenerate OpenAPI client (requires running backend)
make generate-openapi

# Build Docker image
make docker
```

On Windows, use `make.cmd` instead (e.g., `make.cmd test-all`).
