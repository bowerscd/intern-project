# vibe-coded

A small full-stack web application for coordinating two recurring social activities within a friend group:

- **Mealbot** — a meal-credit ledger that tracks who paid for meals, calculates balances between people, and keeps a running history.
- **Happy Hour** — a weekly venue-coordination system with a rotating "tyrant" who picks where the group goes, automatic deadline enforcement, and email/SMS notifications.

The site uses Google OIDC for authentication.

## Project structure

```
backend/            FastAPI API server (Python)
frontend/           Flask web UI (Python + TypeScript)
integration-tests/  End-to-end tests via Docker Compose
```

Each subproject has its own `Makefile` (and `make.cmd` for Windows). See the individual READMEs for details:

- [backend/README.md](backend/README.md) — API endpoints, data model, scheduling, notifications
- [frontend/README.md](frontend/README.md) — pages, proxy architecture, TypeScript modules
- [integration-tests/README.md](integration-tests/README.md) — E2E test setup and categories

## How it works

1. Users authenticate via Google OIDC. The backend issues a signed session cookie; the frontend reverse-proxies API requests so everything stays on one origin.
2. **Mealbot**: any user with the `MEALBOT` claim can record meals ("I paid for Alice") and view the ledger. Balances are computed server-side over configurable date ranges.
3. **Happy Hour**: users with `HAPPY_HOUR` can browse events and locations. Users with `HAPPY_HOUR_TYRANT` are entered into a shuffled rotation. Each Friday at 4 PM a cron job assigns the next tyrant and notifies them. They have until Wednesday noon to submit an event — if they miss three deadlines in a row, their tyrant privilege is revoked and a venue is auto-selected.

## Quick start

### Prerequisites

- Python 3.14+
- Node.js (for TypeScript compilation and frontend tests)
- Docker (for containerised builds and integration tests)

### Backend

```bash
cd backend
make install    # install Python dependencies
make dev        # start FastAPI with auto-reload on :8000
```

### Frontend

```bash
cd frontend
make install    # install Python + Node dependencies
make build      # compile TypeScript
make dev        # start Flask dev server on :5001
```

For layout work without a running backend, set `USE_MOCK=true` — the frontend will serve procedurally generated mock data.

### Integration tests

```bash
cd integration-tests
make test       # spins up Docker Compose stack, runs pytest, tears down
```

## Running tests

```bash
cd backend  && make test        # backend unit tests
cd frontend && make test-all    # Python + TypeScript tests
```

## Building containers

```bash
cd backend  && make docker      # → vibe-coded-backend:latest
cd frontend && make docker      # → vibe-coded-frontend:latest
```

## Windows

Each subproject includes a `make.cmd` that accepts the same target names:

```cmd
cd backend
make.cmd test
make.cmd docker
```
