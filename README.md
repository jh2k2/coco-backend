# Family Engagement Dashboard Backend

> **Purpose:** To collect and process session data from the device, calculate engagement streaks, averages, and sentiment trends, and serve that summarized data through a single API endpoint for the dashboard to use. It’s the invisible engine that turns raw session logs into clean, ready-to-display insights.

This repository implements a minimal FastAPI + PostgreSQL backend that ingests individual session summaries and maintains a seven-day rollup so the dashboard can display up-to-date engagement metrics without doing heavy computations client-side. The service is designed for a single-tenant MVP but uses patterns that scale to more participants as the product grows.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Getting Started](#getting-started)
3. [Data Flow](#data-flow)
4. [Directory Structure](#directory-structure)
5. [Configuration](#configuration)
6. [Database Schema](#database-schema)
7. [Core Modules](#core-modules)
   - [Configuration (`app/config.py`)](#configuration-appconfigpy)
   - [Database Session Management (`app/database.py` & `app/dependencies.py`)](#database-session-management-appdatabasepy--appdependenciespy)
   - [ORM Models (`app/models.py`)](#orm-models-appmodelspy)
   - [Schema Definitions (`app/schemas.py`)](#schema-definitions-appschemaspy)
   - [Authentication Helpers (`app/auth.py`)](#authentication-helpers-appauthpy)
   - [Ingestion & Rollup Service (`app/services/ingest.py`)](#ingestion--rollup-service-appservicesingestpy)
   - [FastAPI Application (`app/main.py`)](#fastapi-application-appmainpy)
8. [API Endpoints](#api-endpoints)
9. [Rollup Computation Details](#rollup-computation-details)
10. [Authentication Model](#authentication-model)
11. [Error Handling & Idempotency](#error-handling--idempotency)
12. [Running Locally](#running-locally)
13. [Project Hygiene](#project-hygiene)
14. [Operational Considerations](#operational-considerations)
15. [Extensibility Notes](#extensibility-notes)
16. [Testing Suite](#testing-suite)
17. [Security Notes](#security-notes)
18. [Deploying to Fly.io](#deploying-to-flyio)

---

## System Overview

The backend exposes two primary HTTP endpoints for product functionality:

1. `POST /internal/ingest/session_summary` accepts raw session telemetry from a trusted upstream device/service. Each request is validated, written to the `sessions` table, and triggers a rollup recomputation for the associated user.
2. `GET /api/dashboard/{user_id}` provides a pre-computed snapshot of the last seven days of engagement for dashboard consumption. The payload mirrors the frontend contract byte-for-byte.

Operational endpoints complement the core API:

- `GET /healthz` returns `200` when the API can reach the database.
- `GET /readyz` verifies database connectivity and echoes the enforced seven-day window for readiness probes.

Between these endpoints, the system handles:

- Upserting user profiles keyed by an external identifier.
- Enforcing idempotency via `session_id`.
- Aggregating engagement data in seven-day windows.
- Translating raw aggregates into domain-friendly metrics (streak status, tone labels, rolling averages).
- Returning a consistent data shape regardless of whether the user has historical activity.
- Emitting structured JSON logs with request IDs while enforcing a locked-down CORS policy that grants the dashboard origin only.

---

## Getting Started

1. **Prerequisites**
   - Python 3.11+ (project developed against 3.12).
   - PostgreSQL with the `pgcrypto` extension available.
   - `pip`, `alembic`, and `uvicorn` (installed via `requirements.txt`).

2. **Create a Virtual Environment**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**
   - Copy `.env.example` to `.env` and adjust the values, or export the variables described in [Configuration](#configuration).
   - Ensure `DATABASE_URL` points at a running PostgreSQL instance.

4. **Apply Database Migrations**

   ```bash
   alembic upgrade head
   ```

5. **Run the API**

   ```bash
   uvicorn app.main:app --reload --env-file .env
   ```

6. **Verify Health**
   - `GET /healthz` confirms the service can reach the database.
   - `GET /readyz` should return `{"status": "ready", "windowDays": 7}`.

See [Running Locally](#running-locally) for a deeper walkthrough, seeding tips, and testing guidance.

---

## Data Flow

1. **Ingestion:** A trusted service calls the ingest endpoint with session metadata (`session_id`, `user_external_id`, `started_at`, `duration_seconds`, `sentiment_score`).
2. **Storage:** The user is created if necessary, the session is inserted (or reported as duplicate), and all sessions for the last seven days are fetched.
3. **Rollup Update:** The service bins sessions per day, calculates activity flags, duration totals (rounded to minutes), mean sentiment, streak, average duration, and current tone. Results are stored in `dashboard_rollups`.
4. **Dashboard Retrieval:** When the dashboard requests data, the stored rollup is returned (or a zeroed-out structure if none exists). Unknown users are created lazily so the dashboard can render an “Empty” state while keeping the contract identical. Each response includes a freshness timestamp.

---

## Directory Structure

```
coco-backend/
├── .env.example               # Template environment variables for local dev
├── app/
│   ├── __init__.py              # Package marker
│   ├── auth.py                  # Auth utilities for bearer tokens
│   ├── config.py                # Environment-driven configuration
│   ├── database.py              # Engine/session factory setup
│   ├── dependencies.py          # FastAPI dependency wrappers
│   ├── db_types.py              # Cross-dialect array types (Postgres + SQLite tests)
│   ├── main.py                  # FastAPI routes and orchestration
│   ├── models.py                # SQLAlchemy ORM models
│   ├── schemas.py               # Pydantic request/response schemas
│   └── services/
│       └── ingest.py            # Ingestion workflow and rollup calculations
├── alembic/                     # Migration environment
│   ├── env.py
│   └── versions/                # Migration scripts
├── alembic.ini                  # Alembic configuration
├── scripts/
│   └── seed_demo_data.py        # Utility to seed a demo participant
├── tests/                       # Pytest suite
└── requirements.txt             # Python dependencies
```

---

## Configuration

`app/config.py` reads environment variables into a Pydantic model. Required values:

- `DATABASE_URL`: SQLAlchemy connection string (e.g., `postgresql+psycopg://user:pass@host/db`).
- `INGEST_SERVICE_TOKEN`: Static bearer token for the ingest endpoint.
- `DASHBOARD_TOKEN_MAP`: Mapping of dashboard bearer tokens to permitted user IDs. Accepts:
  - JSON-like dict via environment tooling, or
  - Comma-separated `token:user` pairs (e.g., `tokenA:user-123,tokenB:user-456`).
    - Use `*` as the user to grant a token access to any user (admin/backoffice).
- `DASHBOARD_ORIGIN`: Exact origin permitted by CORS (e.g., `https://dashboard.example.com`).
- `APP_ENV` (optional, default `development`): `development`, `test`, or `production`. Docs and OpenAPI are disabled automatically when set to `production`.
- `ROLLUP_WINDOW_DAYS`: Locked to `7` for the MVP; the app fails fast if a different value is supplied.

Example shell setup:

```bash
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/coco"
export INGEST_SERVICE_TOKEN="svc-secret-token"
export DASHBOARD_TOKEN_MAP="dash-token-1:user-external-id"
export DASHBOARD_ORIGIN="https://dashboard.local"
```

Errors during configuration parsing raise early with human-readable messages to prevent the application from starting in an invalid state.

---

## Database Schema

The schema follows the provided MVP design:

- `users`: Stores canonical participants. `external_id` matches the frontend `user_id`.
- `sessions`: Stores ingest records with duration, sentiment, and uniqueness enforced by `session_id`.
- `dashboard_rollups`: Stores precomputed arrays for last seven days along with aggregate metrics and `updated_at` timestamp.

Highlights:

- UUID primary keys with `gen_random_uuid()` defaults.
- Check constraints ensure `duration_seconds` (0–86400) and `sentiment_score` (0–1).
- An index on `(user_id, started_at)` accelerates 7-day session scans.
- Array columns use PostgreSQL `BOOLEAN[]`, `INT[]`, and `NUMERIC(4,2)[]` in production; the automated tests use equivalent JSON-backed shims for SQLite to keep feedback fast.

> **Note:** Ensure the `pgcrypto` extension (for `gen_random_uuid()`) is enabled in the target database.

---

## Core Modules

### Configuration (`app/config.py`)

- Defines the `Settings` Pydantic model.
- Parses and validates environment variables, normalizing `DASHBOARD_TOKEN_MAP`.
- Memoizes settings via `get_settings()` so the environment is parsed once per process.
- Locks `ROLLUP_WINDOW_DAYS` to `7` and enforces presence of `DASHBOARD_ORIGIN`; throws meaningful errors when env vars are missing or malformed.

### Database Session Management (`app/database.py` & `app/dependencies.py`)

- `database.py` creates the SQLAlchemy engine (with `pool_pre_ping`) and session factory (`SessionLocal`).
- Adapts automatically to SQLite with an in-memory static pool for the pytest suite while defaulting to PostgreSQL in runtime environments.
- `dependencies.py` exposes `get_db()` dependency that opens a session per request and ensures cleanup.

### Dialect-Agnostic Array Types (`app/db_types.py`)

- Provides `TypeDecorator` helpers that store booleans, integers, and decimals as PostgreSQL ARRAY fields in production while falling back to JSON columns in SQLite-based tests.
- Preserves decimal precision for sentiment scores and keeps list ordering consistent regardless of database backend.

### ORM Models (`app/models.py`)

- `User`: Represents dashboard participants; includes relationships to `Session` and `DashboardRollup`.
- `Session`: Stores individual session summaries with constraints and unique `session_id`.
- `DashboardRollup`: Holds daily arrays and aggregated metrics; `current_tone` is constrained to the allowed values.
- Defines the `idx_sessions_user_started` index for efficient queries.

### Schema Definitions (`app/schemas.py`)

- `SessionSummaryIngestRequest`: Validates ingest payloads (e.g., ensures timezone-aware `started_at`).
- `DashboardResponse`: Models the exact response contract expected by the frontend, including nested types for last session, streak, average duration, and sentiment trend.
- Validators enforce 7-element arrays to guarantee correct response shape.

### Authentication Helpers (`app/auth.py`)

- `_bearer_token()` extracts the bearer token from the `Authorization` header, raising `401` for missing/invalid headers.
- `require_service_token()` authenticates ingest calls against `INGEST_SERVICE_TOKEN`.
- `authorize_dashboard_access()` authenticates dashboard requests using `DASHBOARD_TOKEN_MAP`, supporting a wildcard (`*`) for admin tokens and enforcing per-user access otherwise.

### Ingestion & Rollup Service (`app/services/ingest.py`)

- `ingest_session_summary()` orchestrates user upsert, duplicate detection, session insertion, and rollup recompute.
- `_get_or_create_user()` finds or creates a `User` row based on `external_id`.
- `_session_exists()` checks `session_id` uniqueness to enforce idempotency.
- `recompute_dashboard_rollup()`:
  - Collects sessions in the configured window.
  - Bins sessions by day (UTC), computes per-day flags, rounded minutes, and mean sentiment.
  - Credits each session to the UTC day of its `started_at` timestamp (even if it crosses midnight).
  - Tracks `last_session_at` based on `started_at + duration`.
  - Calculates `avg_duration_minutes` across non-zero days (rounded half-up).
  - Determines `current_tone` from the most recent non-null sentiment (>=0.61 positive, 0.40–0.60 neutral, <0.40 negative; default neutral if no data).
  - Upserts the `DashboardRollup` row.
  - Raises if invoked with a window different from seven days to guarantee schema consistency.
- Helper functions use `Decimal` arithmetic to maintain precision and enforce rounding rules.

### FastAPI Application (`app/main.py`)

- Instantiates the FastAPI app, disables `/docs` and `/openapi.json` automatically when `APP_ENV=production`, and only calls `Base.metadata.create_all` in development/test.
- Applies strict CORS configuration that whitelists exactly one origin (`DASHBOARD_ORIGIN`) and exposes an `X-Request-ID` header for tracing.
- Adds structured request logging (request id, user id, path, duration) without ever echoing bearer tokens.
- Exposes health probes:
  - `GET /healthz` verifies database connectivity.
  - `GET /readyz` ensures the service can reach the database and confirms the seven-day window contract.
- Defines the two primary routes:
  - `POST /internal/ingest/session_summary`: Validates auth, processes ingestion, handles unique constraint errors gracefully, and returns `{"status": "ok"}` or `{"status": "duplicate"}` (always `200 OK`).
  - `GET /api/dashboard/{user_id}`: Authenticates access, lazily creates missing users, returns zeroed arrays for new participants, and timestamps `lastUpdated`.
- Publishes helper constant (`WINDOW_DAYS`) that documents the dashboard contract.
- Utility functions:
  - `_build_dashboard_response()` merges raw rollup data with derived values.
  - `_calculate_streak_days()` counts consecutive `True` values from the end of `dailyActivity`.
  - `_is_unique_violation()` detects duplicate insert attempts from SQLAlchemy exceptions.

---

## API Endpoints

### POST `/internal/ingest/session_summary`

- **Authorization:** Bearer token matching `INGEST_SERVICE_TOKEN`.
- **Request Body:**

  ```json
  {
    "session_id": "uuid-or-unique-string",
    "user_external_id": "string",
    "started_at": "2025-10-22T14:30:00Z",
    "duration_seconds": 720,
    "sentiment_score": 0.68
  }
  ```

- **Behavior:**
  - Validates payload ranges and timezone awareness.
  - Creates the user record if needed.
  - Checks for existing `session_id`; returns duplicate without side effects.
  - Inserts the session and recomputes the user rollup.
  - Returns `{"status": "ok"}` or `{"status": "duplicate"}` (always `200 OK`).
  - Invalid payloads bubble up as FastAPI `422` responses that identify the offending field(s).

- **Idempotency:** Guaranteed via `session_id` uniqueness.

#### Example Request

Generate a payload with a unique `session_id` and the bearer token from `INGEST_SERVICE_TOKEN`:

```bash
curl -X POST http://localhost:8000/internal/ingest/session_summary \
  -H "Authorization: Bearer ${INGEST_SERVICE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
        "session_id": "demo-session-001",
        "user_external_id": "demo-user",
        "started_at": "2025-10-22T14:30:00Z",
        "duration_seconds": 900,
        "sentiment_score": 0.66
      }'
```

To fabricate fresh payloads on demand, this helper prints a ready-to-send JSON body:

```bash
python3 - <<'PY'
import json, uuid
from datetime import datetime, timezone

payload = {
    "session_id": f"demo-{uuid.uuid4()}",
    "user_external_id": "demo-user",
    "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "duration_seconds": 900,
    "sentiment_score": 0.66,
}
print(json.dumps(payload, indent=2))
PY
```

Pipe the output into `curl --data @-` to avoid saving a temporary file. Once the ingest call returns `{"status":"ok"}`, fetch the dashboard snapshot for the same `user_external_id` to confirm the rollup updated.

### GET `/api/dashboard/{user_id}`

- **Authorization:** Bearer token that maps to `user_id` (or wildcard `*`).
- **Response:**

  ```json
  {
    "lastSession": {"timestamp":"ISO8601"},
    "streak": {"days":N,"dailyActivity":[bool,bool,bool,bool,bool,bool,bool]},
    "avgDuration": {"minutes":N,"dailyDurations":[int,int,int,int,int,int,int]},
    "toneTrend": {"current":"positive|neutral|negative","dailySentiment":[num,num,num,num,num,num,num]},
    "lastUpdated": "ISO8601"
  }
  ```

- **Behavior:**
  - Lazily creates the user if absent and returns zeroed arrays so the frontend can render an “Empty” state.
  - Loads or synthesizes rollup data for a fixed seven-day window.
  - Calculates streak dynamically on each response to reflect current time.
  - Normalizes sentiment decimals to floats with two decimal places.
  - Emits an `X-Request-ID` header you can forward to logs for traceability.

#### Example Request

```bash
curl http://localhost:8000/api/dashboard/demo-user \
  -H "Authorization: Bearer dash-token-1"
```

Replace the bearer token with one of the entries in `DASHBOARD_TOKEN_MAP`. The response payload mirrors the dashboard contract regardless of whether the user already has activity.

### GET `/healthz`

- **Purpose:** Connectivity check for load balancers and uptime monitors.
- **Behavior:** Executes a lightweight `SELECT 1` against the database and returns `{"status":"ok"}` when successful.

### GET `/readyz`

- **Purpose:** Readiness probe for orchestrators.
- **Authorization:** None. The endpoint is intentionally public so callers can block on readiness before presenting the dashboard.
- **Behavior:** Confirms the database is reachable, ensures metadata can be queried, and returns `{"status":"ready","windowDays":7}` to reaffirm the fixed rollup contract.

---

## Rollup Computation Details

1. **Window Definition:** Locked to seven days for the MVP. The window includes today and the preceding six days in UTC.
2. **Daily Bucketing:** Sessions are grouped by UTC date of `started_at`.
3. **Daily Metrics:**
   - `daily_activity`: `True` if any session exists on that day.
   - `daily_durations`: Sum of `duration_seconds` per day, converted to minutes and rounded half-up.
   - `daily_sentiment`: Mean of `sentiment_score` per day, rounded to two decimals. Days without sessions store `null`.
4. **Last Session Timestamp:** Tracks the end time (`started_at + duration`) of the most recent session in the window.
5. **Client Status Logic:** The API exposes only the timestamp of the most recent session; dashboards derive any status labels on their side.
6. **Average Duration:** Mean of non-zero `daily_durations`, rounded half-up. Returns `0` if the user had no activity.
7. **Current Tone:** Determined by scanning from the newest daily sentiment backward until a non-null value is found.
8. **Persistence:** The rollup is inserted if new, otherwise updated in place with a fresh `updated_at`.

This eager computation ensures dashboard reads are cheap and deterministic.

---

## Authentication Model

- Ingest endpoint uses a single shared secret (`INGEST_SERVICE_TOKEN`). Requests without the exact token receive `401 Unauthorized`.
- Dashboard endpoint uses a token-to-user map (`DASHBOARD_TOKEN_MAP`):
  - Key: bearer token presented by the frontend or proxy.
  - Value: external user ID allowed for that token, or `*` for admin access.
  - Tokens not present in the map return `401`; mismatched user/token pairs return `403`.

This minimal model is sufficient for an MVP and can be upgraded to OAuth/JWT later.

---

## Error Handling & Idempotency

- Input validation relies on Pydantic. Invalid payloads produce informative `422` responses automatically.
- Duplicate sessions (`session_id` conflict) are caught before insert; if a race slips through, the `IntegrityError` handler returns a duplicate response.
- Database operations use SQLAlchemy sessions with explicit commits inside routes to surface errors predictably.
- Dashboard requests for unknown users return `200 OK` with a zeroed-out structure so the frontend can render an empty state without special-case logic.

---

## Running Locally

1. **Install Dependencies**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Prepare PostgreSQL**

   - Start a PostgreSQL instance.
   - Create the target database (e.g., `coco`).
   - Enable `pgcrypto`: `CREATE EXTENSION IF NOT EXISTS pgcrypto;`

3. **Configure Environment**

   Either export the environment variables described in [Configuration](#configuration) or copy `.env.example` to `.env` and fill in local secrets before you start the server.

4. **Run Migrations**

   ```bash
   alembic upgrade head
   ```

5. **(Optional) Seed Demo Data**

   ```bash
   PYTHONPATH=. python scripts/seed_demo_data.py --user demo-user --reset
   ```

   The helper script runs entirely against the configured database. Use `--user <external_id>` to target the same user IDs you map in `DASHBOARD_TOKEN_MAP`. Re-run with `--reset` whenever you want to wipe and reseed a clean seven-day window.

6. **Run the API**

   ```bash
   uvicorn app.main:app --reload --env-file .env
   ```

7. **Smoke Test**

   - POST a session summary with the service token.
   - GET the dashboard data with the mapped dashboard token.
   - Use the sample commands in [POST `/internal/ingest/session_summary`](#post-internalingestsession_summary) to generate and send payloads quickly.

8. **Run Tests**

   ```bash
   pytest
   ```

   (If you have not installed the package, run `PYTHONPATH=. pytest` to mirror the project’s CI invocation.)

---

## Project Hygiene

- Source control now ignores generated artifacts such as `__pycache__/`, `.pytest_cache/`, `.env*`, and local virtual environments via the project-level `.gitignore`.
- Keep the checked-in tree focused on source by running `find app tests -name '__pycache__' -type d -prune -exec rm -rf {} +` or deleting `.pytest_cache/` after local test runs.
- `.env.example` documents safe defaults; keep your personal `.env` out of source control and store real secrets in environment-specific managers.
- When upgrading dependencies, prefer recreating the virtual environment (`rm -rf .venv && python3 -m venv .venv`) to avoid stale packages.

---

## Demo Tokens & Local Auth Flow

- **Ingest token:** `INGEST_SERVICE_TOKEN` in `.env` must match the bearer token your ingest client sends to `/internal/ingest/session_summary`.
- **Dashboard tokens:** `DASHBOARD_TOKEN_MAP` is a comma-separated list of `token:user_id` pairs. The dashboard must present the token that maps to the requested `user_id`. Use `*` as the user id to grant wildcard access (reserved for internal tooling).
- **CORS:** Only the origin specified in `DASHBOARD_ORIGIN` is allowed. Set it to your local dashboard dev server (e.g., `http://localhost:3000`) and update it to the production hostname before deploying.
- **Readiness:** `/readyz` requires no auth, making it safe for the frontend to poll before rendering the dashboard UI.

Keep tokens in a secrets manager for shared environments and rotate them regularly. The sample values in `.env` are suitable only for local development.

---

## Operational Considerations

- **Schema Management:** Run Alembic migrations (`alembic upgrade head`) as part of each deploy; `Base.metadata.create_all` only runs in local/dev environments.
- **Connection Pooling:** SQLAlchemy’s default pool is sufficient for early load; adjust options (pool size, timeouts) using query parameters if needed.
- **Transport Security:** Terminate HTTPS at the edge and enable HSTS on the proxy; the API assumes requests arrive over TLS.
- **Secrets & Tokens:** Store `INGEST_SERVICE_TOKEN` and dashboard tokens in a secrets manager, rotate them on a schedule, and ensure logs never include raw values. Wildcard (`*`) admin tokens should be distributed only to trusted internal tooling, never shipped with public clients.
- **Auth Delivery:** Preferred flow is a same-origin cookie session where the proxy injects the `Authorization` header. If bearer tokens must reach the browser, deliver them via one-time link and persist only in `sessionStorage`, leveraging the strict single-origin CORS policy.
- **Monitoring & Observability:** Forward structured request logs (with `X-Request-ID`) to your logging stack and wire `/healthz` and `/readyz` probes into your deployment platform. Track ingest volume, rollup latency, and error rates to keep the dashboard fresh.
- **Time Zones:** All data is normalized to UTC. Any UI localization should be handled client-side.

---

## Extensibility Notes

- **Multiple Participants:** When expanding to more users, consider adding paginated listing endpoints and background jobs for recalculations.
- **Historical Windows:** To support flexible reporting windows, store more than seven days of sessions and parameterize rollup length per request.
- **Advanced Auth:** Replace static tokens with JWT or integrate with an identity provider as needed.
- **Additional Metrics:** Extend the rollup service with new derived fields (e.g., median duration, sentiment volatility) while keeping the response contract versioned.
- **Testing:** Expand the pytest suite alongside new features (see [Testing Suite](#testing-suite)) to preserve rollup guarantees and auth invariants.

---

## Testing Suite

- **Framework:** Pytest (see `requirements.txt`). The suite boots the FastAPI app against an in-memory SQLite database that mimics PostgreSQL array semantics via `app/db_types.py`.
- **Coverage:**
  - `tests/test_rollup.py` validates streak math, tone thresholds, recent/warning/stale cutoffs, and the empty-state response when a user is first seen.
  - `tests/test_auth_and_cors.py` ensures auth failures return the correct codes and that CORS only approves the configured dashboard origin.
  - `tests/test_ingest.py` confirms ingest idempotency returns `{"status":"duplicate"}` with `200` once a session ID repeats.
- `tests/test_helpers.py` locks down the helper utilities (streak calculation, rounding, tone classification, duplicate detection) so regressions are caught before hitting the API layer.
- **Running:** Activate your virtualenv, install dependencies, and execute `pytest` (for example, `source .venv/bin/activate && pytest`). Add new tests with clear, deterministic expectations whenever you change rollup math, security, or response formats.

---

## Security Notes

- **Secret Storage:** Both `INGEST_SERVICE_TOKEN` and entries in `DASHBOARD_TOKEN_MAP` belong in a secrets manager. Never commit them to source control or surface them in logs/metrics.
- **Token Handling:** Prefer proxy-injected headers backed by same-origin cookies. If bearer tokens must reach the browser, issue single-use links, store the token in `sessionStorage`, and rely on the restrictive CORS policy (`DASHBOARD_ORIGIN`).
- **Admin Tokens:** If you issue wildcard (`*`) dashboard tokens, keep them on internal tooling only, rotate them regularly, and scope RBAC as soon as you add multiple users.
- **Transport:** Terminate TLS in front of the API and enforce HSTS at the proxy. All timestamps and rollups assume clients and servers communicate over HTTPS.
- **Logging:** Structured logs deliberately omit secrets; continue redacting inbound headers or payloads if you expand the request logging surface.

---

## Deploying to Fly.io

1. **Install & authenticate.** Install [`flyctl`](https://fly.io/docs/flyctl/install/) and run `fly auth login`.
2. **Name the app.** Update `app` and (optionally) `primary_region` inside `fly.toml` before your first deploy.
3. **Provision Postgres.** Create a managed database (`fly postgres create --name coco-db --region iad`) and note the app name it returns.
4. **Attach the database.** `fly postgres attach --app <your-app-name> coco-db` creates the `DATABASE_URL` secret automatically. The backend accepts `postgres://` URLs and rewrites them to the `psycopg` driver at runtime.
5. **Configure secrets.** Set production tokens and the dashboard origin:  
   `fly secrets set INGEST_SERVICE_TOKEN=... DASHBOARD_TOKEN_MAP=... DASHBOARD_ORIGIN=https://dashboard.example.com`
6. **Deploy the app.** Run `fly deploy`. The Dockerfile builds a Python 3.11 image, and the `[deploy]` `release_command` runs `alembic upgrade head` so schema migrations apply before new machines start.
7. **Scale & verify.** Adjust resources if necessary (`fly scale memory 1024`) and watch the rollout with `fly status` and `fly logs`.
8. **Run utilities.** Use `fly ssh console --command "python -m scripts.seed_demo_data"` to seed demo data or run one-off tasks inside the deployed container.

The Fly runtime sets `APP_ENV=production` and keeps machines idle-friendly via `auto_start_machines/auto_stop_machines`; tweak these in `fly.toml` if you need always-on capacity.

---

This documentation captures the current MVP implementation and the intent behind every module so future contributors can quickly understand how raw session logs are transformed into the dashboard’s “ready-to-display insights.”
