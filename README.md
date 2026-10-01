# Dataset Request Desk

Internal platform that replaces the dataset-request spreadsheet:
- **Clients** submit dataset requests and accept or reject deliveries.
- **Operators** move requests through the workflow, assign recorded robot episodes, and import episode metadata.
- **Admins** also manage users.

**Stack:** FastAPI + SQLAlchemy 2 + Alembic on PostgreSQL 16, a small React (Vite) UI behind nginx, and Docker Compose. **Stretch item: real-time updates (SSE).** Operators see new requests and status changes appear live.

Design reasoning, trade-offs and incidents are in [NOTES.md](NOTES.md).

## Quick start

Requires Docker (Docker Desktop or OrbStack).

```bash
docker compose up --build
```

| What | Where |
|---|---|
| Web UI | http://localhost:8080 |
| API | http://localhost:8000 (also proxied at http://localhost:8080/api) |
| Health | http://localhost:8080/health |
| API docs (OpenAPI) | http://localhost:8000/docs |

On start, the API container runs the migrations, creates the seed users, and imports `seed/episodes.csv`. All three steps are idempotent, so restarting is always safe.

### Seed users

| Email | Password | Role |
|---|---|---|
| admin@example.com | admin123 | admin |
| ops1@example.com | ops123 | operator |
| ops2@example.com | ops123 | operator |
| client-a@example.com | client123 | client (Acme Robotics) |
| client-b@example.com | client123 | client (Beta Labs) |

Passwords are stored as bcrypt hashes. To see the live updates, log in as an operator in one browser window and as a client in a private window, then create a request as the client.

## Tests

```bash
make test        # runs the full suite inside the api image against a separate drd_test database
```

Without Docker for the API (Postgres still needed): run `docker compose up -d db`, then
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest
```

The suite (168 tests) runs against real PostgreSQL, using the real migrations (down, then up). It focuses on what the brief cares about:

| Area | File |
|---|---|
| Authorization: roles, own-requests-only, 401/403/404 | `test_auth.py`, `test_users.py`, `test_requests.py` |
| Status transitions: every (from, to, role) combination, 75 cases | `test_workflow.py` |
| Assignment rules: quality, one request per episode, delivery threshold, all-or-nothing | `test_assignments.py`, `test_models.py` |
| Import: every messy-row case, idempotency on the real seed file, Excel BOM/CRLF | `test_import.py` |
| Analytics, health, structured logging, SSE broker | `test_analytics.py`, `test_ops.py`, `test_events.py` |

CI (GitHub Actions) runs the backend tests against Postgres and builds the frontend on every push.

## Importing episodes

From the CLI:
```bash
docker compose exec api python -m app.cli import-episodes /seed/episodes.csv
```
Over HTTP (operator or admin session):
```bash
curl -c jar -H 'Content-Type: application/json' -d '{"email":"ops1@example.com","password":"ops123"}' localhost:8080/api/auth/login
curl -b jar -F file=@seed/episodes.csv localhost:8080/api/episodes/import
```
Both print a report: `rows_read`, `inserted`, `updated`, `unchanged`, and `skipped` (with line number and reason for each). The seed file gives **191 read, 171 inserted, 20 skipped**. Running it again gives **171 unchanged**. The cleaning rules are in NOTES.md.

## API overview

All endpoints except `POST /api/auth/login` and `/health` require a session cookie.

| Method & path | Who | Purpose |
|---|---|---|
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | anyone | session |
| `GET/POST /api/users`, `PATCH /api/users/{id}` | admin | list, create, change role, deactivate |
| `POST /api/requests` | client | create a request |
| `GET /api/requests[?status=]` | all | clients see only their own |
| `GET /api/requests/{id}` | all | detail, history, assigned episodes, and the transitions allowed for the caller |
| `POST /api/requests/{id}/transitions` | by step | `{to_status, note}`; clients accept/reject, staff do the rest |
| `POST /api/requests/{id}/assignments` | staff | `{episode_ids: [...]}`, all-or-nothing |
| `DELETE /api/requests/{id}/assignments/{episode_id}` | staff | unassign |
| `GET /api/episodes?task_name=&quality=&robot_id=&unassigned_only=&limit=&offset=` | staff | episode browser |
| `POST /api/episodes/import` | staff | CSV upload (multipart field `file`) |
| `GET /api/analytics?from=YYYY-MM-DD&to=YYYY-MM-DD` | staff | see below |
| `GET /api/events` | staff | Server-Sent Events stream |
| `GET /health` | anyone | 200 if the database is reachable, else 503 |

Every request writes one JSON log line, with `method, path, status, duration_ms, user_id`.

## Analytics, and how it behaves at volume

`GET /api/analytics` returns four things for an inclusive date range (UTC days):
- episodes per day per robot;
- request counts by status;
- the median time from submitted to first delivery;
- the top 5 task names by number of *good* episodes.

All aggregation runs in PostgreSQL (`GROUP BY`, `percentile_cont`). Python only shapes the result.

**Indexes designed for these queries:**
- `(recorded_at, robot_id)` for the per-day counts;
- a **partial** index `(recorded_at, task_name) WHERE quality = 'good'` for the top-5;
- `(to_status, request_id)` on the status-event log for the median.

**Measured with 200,000 generated episodes** (`seed/generate_episodes.py`; Postgres 16 in Docker on a laptop):

| Query | 1-month range | 1-year range (all rows) |
|---|---|---|
| episodes per day per robot | 17.6 ms (index-only scan, 0 heap fetches) | 88.7 ms (seq scan) |
| top 5 tasks by good episodes | 8.8 ms (index-only scan on the partial index) | 59.6 ms (parallel seq scan) |

The import ran at 200,000 rows in about 69 s. A re-run took about 63 s and wrote nothing, so the time is spent in Python parsing and batch round trips, not in database writes.

**At 5 million episodes:**
- Typical ranges (days to weeks) stay index-only and fast. Cost grows with the number of rows *in the range*, not with the table size.
- Year-long ranges become full scans of millions of rows, roughly 2–3 s, repeated on every dashboard load. The fix is to stop counting raw rows: keep a daily rollup table `(day, robot_id, task_name, quality, count)`, updated by the import (or a materialized view refreshed after imports). Analytics would then read about 40k pre-aggregated rows instead of 5M.
- The episode list's `count(*)` for pagination would also get slow. Switch to keyset pagination with an estimated total.
- Monthly range partitioning of `episodes` by `recorded_at` would keep indexes small and make archiving cheap.
- The importer keeps one file's cleaned rows in memory for duplicate detection, which is fine for hundreds of thousands of rows. For multi-million-row files, stage into a temporary table and deduplicate in SQL.

## Project layout

```
backend/   FastAPI app (app/), Alembic migrations (alembic/), tests (tests/)
frontend/  React + Vite UI, nginx config
seed/      users.json, episodes.csv, generator for large files
```
