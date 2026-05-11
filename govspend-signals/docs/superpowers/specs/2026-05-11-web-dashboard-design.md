# govspend Web Dashboard — Design Spec

> Created: 2026-05-11

## Goal

Add a browser-based dashboard to govspend-signals that displays all seven signal panels (signal feed, source breakdown, sector rotation, watchlist activity, catalyst calendar, basket, options plays) with auto-refresh and WebAuthn passkey authentication. Runs locally with `govspend web` and deploys to Fly.io with the same command.

## Architecture

A single FastAPI app (`govspend_signals/web.py`) reads from the same SQLite database the ingestors write to. No new data layer. The CLI remains fully functional independently.

The app serves:
- `/api/*` — JSON endpoints, one per panel + auth endpoints
- `/` — static `index.html` + `app.js` + `style.css` from `govspend_signals/web_static/`

Session authentication uses a signed cookie (`itsdangerous`). All `/api/*` endpoints except `/api/auth/*` return HTTP 401 if unauthenticated.

### New files

```
govspend_signals/
├── web.py                  # FastAPI app + all API routes
└── web_static/
    ├── index.html          # single page, all 7 panels
    ├── app.js              # fetch + setInterval auto-refresh
    └── style.css           # dark theme
```

### Modified files

```
govspend_signals/cli.py     # add `web` subcommand → starts uvicorn
govspend_signals/storage.py # add credentials table + CRUD methods
pyproject.toml              # add [web] optional dep group
Dockerfile                  # new — for Fly.io deployment
fly.toml                    # new — Fly.io config
```

## API Endpoints

### Data endpoints

All accept optional `?hours=N` query param (default 24). All require authentication.

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/signals` | Recent signals, newest first, 100/page. Accepts `?page=N`. |
| GET | `/api/sources` | Signal counts per source for the window. |
| GET | `/api/sector-rotation` | Current vs prior window counts + pct change per sector. Prior window = 7× current window. |
| GET | `/api/watchlist` | Per-ticker signal count + total contract USD. |
| GET | `/api/catalysts` | Upcoming catalyst events from the signals store. |
| GET | `/api/basket` | Ethical-screen positions with weights (contract-weighted by default). |
| GET | `/api/options` | Catalyst-driven options plays grouped by catalyst date. |

### Auth endpoints

No authentication required on these routes.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/auth/status` | `{"registered": bool, "authenticated": bool}` |
| POST | `/api/auth/register/begin` | Start passkey registration — returns `PublicKeyCredentialCreationOptions` |
| POST | `/api/auth/register/finish` | Complete registration, store credential, set session cookie |
| POST | `/api/auth/login/begin` | Start passkey login — returns challenge + credential IDs |
| POST | `/api/auth/login/finish` | Verify WebAuthn assertion, set session cookie |
| POST | `/api/auth/logout` | Clear session cookie |

## Frontend

Single `index.html`. Dark theme matching the terminal dashboard. No JS framework — plain `fetch` + DOM manipulation.

### Layout

```
┌─────────────────────────────────────────────┐
│  govspend  [last updated 09:11:30]  [logout] │
├──────────────────┬──────────────────────────┤
│  Signal Feed     │  Source Breakdown        │
│  (scrollable,    │  (bar chart per source)  │
│   newest first)  ├──────────────────────────┤
│                  │  Sector Rotation         │
│                  │  (↑↓ % change, bars)     │
├──────────────────┴──────────────────────────┤
│  Watchlist Activity  │  Catalyst Calendar   │
│  (ticker table)      │  (upcoming events)   │
├──────────────────────┴──────────────────────┤
│  Basket              │  Options Plays       │
│  (allocation table)  │  (grouped by date)   │
└─────────────────────────────────────────────┘
```

Responsive: on narrow screens the two-column sections stack vertically.

### Auto-refresh

`setInterval` polls all seven `/api/*` endpoints every 30 seconds and updates the DOM in place. A "last updated" timestamp in the header ticks on each refresh. No full page reload.

### Auth flow (client-side)

1. On load, JS calls `GET /api/auth/status`.
2. If `authenticated: false` and `registered: true` → show login screen with "Sign in with passkey" button.
3. If `authenticated: false` and `registered: false` → show registration screen with "Register passkey" button.
4. If `authenticated: true` → show dashboard, start auto-refresh loop.
5. Logout button calls `POST /api/auth/logout` and reloads to login screen.

## Passkey Auth

Uses `py-webauthn` on the server and the browser's built-in `navigator.credentials` WebAuthn API. No third-party JS libraries.

### Registration (first-time setup)

1. User clicks "Register passkey"
2. JS → `POST /api/auth/register/begin` → server generates challenge, stores in session, returns `PublicKeyCredentialCreationOptions`
3. Browser calls `navigator.credentials.create()` → Touch ID / Face ID / hardware key prompt
4. JS → `POST /api/auth/register/finish` with attestation
5. Server verifies + stores credential (public key, credential ID, sign count) in `credentials` table
6. Session cookie set → dashboard loads

### Login (subsequent visits)

1. User clicks "Sign in with passkey"
2. JS → `POST /api/auth/login/begin` → server returns challenge + allowed credential IDs
3. Browser calls `navigator.credentials.get()` → biometric prompt
4. JS → `POST /api/auth/login/finish` with assertion
5. Server verifies signature + increments sign count → session cookie set

### Storage

New `credentials` table in the existing `signals.db`:

```sql
CREATE TABLE IF NOT EXISTS credentials (
    id          TEXT PRIMARY KEY,   -- base64url credential ID
    public_key  BLOB NOT NULL,      -- COSE-encoded public key
    sign_count  INTEGER NOT NULL DEFAULT 0,
    name        TEXT,               -- optional human label ("MacBook Touch ID")
    created_ts  INTEGER NOT NULL
);
```

Supports multiple credentials (MacBook Touch ID + iPhone + YubiKey all register separately).

### Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `DASHBOARD_ORIGIN` | `http://localhost:8000` | WebAuthn relying party origin — must match browser URL exactly |
| `DASHBOARD_SECRET` | generated on first run, stored in DB | Signs session cookies |
| `DASHBOARD_HOST` | `127.0.0.1` | Bind address |
| `DASHBOARD_PORT` | `8000` | Port |

## CLI

New `web` subcommand added to `cli.py`:

```bash
govspend web                          # http://localhost:8000
govspend web --host 0.0.0.0           # expose on network
govspend web --port 9000
govspend web --db /data/signals.db    # explicit DB path (for Docker)
```

## Deployment (Fly.io)

```toml
# fly.toml
app = "govspend-signals"

[build]
  dockerfile = "Dockerfile"

[mounts]
  source = "govspend_data"
  destination = "/data"

[http_service]
  internal_port = 8000
  force_https = true

[env]
  DASHBOARD_ORIGIN = "https://govspend-signals.fly.dev"
```

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e ".[full,web]"
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8000
CMD ["govspend", "web", "--host", "0.0.0.0", "--db", "/data/signals.db"]
```

Secrets (`EDGAR_USER_AGENT`, `DASHBOARD_SECRET`) set via `fly secrets set`.

Ingest runs as a scheduled Fly Machine (cron) against the same `/data/signals.db` volume.

## New optional dependency group

```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "py-webauthn>=2.1",
    "itsdangerous>=2.1",
]
```

Install with: `pip install -e ".[full,web]"`

## Testing

- Unit tests for each `/api/*` endpoint (mock Storage, assert JSON shape)
- Unit tests for auth endpoints (mock py-webauthn, test happy path + error cases)
- No browser automation tests — passkey registration requires hardware interaction

## What this does NOT include

- Multi-user accounts (single-user dashboard only)
- Real-time WebSocket push (30s polling is sufficient)
- Email/Telegram config UI (stay in config.toml)
- Historical charting (static tables only in v1)
