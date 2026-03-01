# vibe-coded (backend)

FastAPI backend powering two social-coordination tools — **Mealbot** and **Happy Hour**.

## Features

### Mealbot

A meal-credit ledger that tracks who paid for meals between users.
Users record transactions, view a global or personal ledger, and check per-person balance summaries over optional date ranges.

### Happy Hour

A weekly venue-coordination system built around a rotating **"tyrant"** — one person per week whose job is to pick where the group goes.

- **Locations** — a shared venue directory (name, address, coordinates, URL, open/closed status).
- **Events** — scheduled happy hours tied to a location, with iCalendar-attachment email notifications.
- **Tyrant rotation** — a round-robin cycle where users are shuffled each cycle. A cron job assigns the next tyrant every Friday at 4 PM PST and gives them until Wednesday noon to submit an event. If they miss the deadline, a venue is auto-selected and three consecutive misses revoke their tyrant privilege.

### Authentication

OIDC Authorization Code flow (Google, plus a test provider for local dev), implemented as a Backend-for-Frontend pattern with signed session cookies.

- Login, registration, legacy-account claiming
- Bitmask-based permission system: `BASIC`, `ADMIN`, `MEALBOT`, `COOKBOOK`, `HAPPY_HOUR`, `HAPPY_HOUR_TYRANT`
- Self-service claim toggles (users cannot modify `ADMIN` or `BASIC`)
- Rate-limited auth endpoints via `slowapi`

### Notifications

Email and SMS (via carrier email-to-SMS gateways) for:

- Happy hour event announcements (HTML email with iCalendar attachment + plain-text SMS)
- Tyrant assignment and "on deck" heads-up messages

### Scheduling

Two APScheduler cron jobs:

| Job | When | What |
|-----|------|------|
| `assign_tyrant` | Friday 4:00 PM PST | Advance the rotation, notify the assigned tyrant and next-on-deck |
| `auto_select_happy_hour` | Wednesday 12:00 PM PST | If no event submitted, mark tyrant as missed, auto-pick a venue, send notifications |

## API structure

All active routes live under `/api/v2/`. Legacy v0/v1 endpoints return `410 Gone`.

| Group | Prefix | Key endpoints |
|-------|--------|---------------|
| Health | `/healthz` | Liveness/readiness probe |
| Auth | `/api/v2/auth/` | `login/{provider}`, `register/{provider}`, `callback/{provider}`, `complete-registration`, `claim-account` |
| Account | `/api/v2/account/` | `GET/PATCH profile`, `PATCH claims` |
| Mealbot | `/api/v2/mealbot/` | `GET ledger`, `GET ledger/me`, `GET summary`, `POST record` |
| Happy Hour | `/api/v2/happyhour/` | `GET/POST locations`, `GET/PATCH locations/{id}`, `GET/POST events`, `GET events/upcoming`, `GET rotation` |

## Data model

Six SQLAlchemy tables managed by Alembic:

| Table | Purpose |
|-------|---------|
| `accounts` | Users — username, email, phone, OIDC identity, claims bitmask |
| `receipts` | Meal credit records — payer, recipient, credits, timestamp |
| `HappyHourLocations` | Venues — name, address, coordinates, URL, open/closed |
| `HappyHourEvents` | Scheduled events — location, datetime, tyrant, description |
| `HappyHourTyrantRotation` | Rotation assignments — cycle, position, deadline, status |
| `account_claim_requests` | Legacy-account claim requests — provider, sub, status |

## Configuration

Settings are resolved in order: `settings.json` → environment variables → defaults.
See [.env.example](.env.example) for all supported variables.

Key settings:

| Variable | Purpose |
|----------|---------|
| `SESSION_SECRET` | Signs session cookies (required) |
| `DATABASE_URI` | SQLAlchemy connection string (default: in-memory SQLite) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OIDC credentials |
| `SMTP_URI` / `MAIL_SENDER` | Outgoing email |
| `DEV` | Enables dev mode (relaxed CORS, verbose errors, test OIDC provider) |

## Development

```bash
# Install dependencies
make install

# Run with auto-reload
make dev

# Run tests
make test

# Lint / format
make lint
make format

# Build Docker image
make docker
```

On Windows, use `make.cmd` instead (e.g., `make.cmd test`).
