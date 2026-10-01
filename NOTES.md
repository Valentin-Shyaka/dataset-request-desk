# Notes

## 1. Design

### Data model

```
users (id, email UNIQUE, name, organisation, role CHECK, password_hash, is_active)
  │
  ├──< dataset_requests (id, client_id FK, task_name, episodes_requested CHECK > 0,
  │        deadline, notes, status CHECK, created_at, updated_at)
  │        │
  │        ├──< request_status_events (request_id, from_status, to_status, actor_id FK, note, created_at)
  │        │        append-only audit log, one row per status change (including creation)
  │        │
  │        └──< assignments (request_id FK, episode_id FK UNIQUE, assigned_by_id, assigned_at)
  │
robots (id) ──< episodes (episode_id PK, robot_id FK, task_name, recorded_at timestamptz,
                          duration_seconds CHECK > 0, operator_name NULL, quality CHECK, imported_at)
```

- **`episode_id` is the primary key.** It's the natural key from the recording system, so a duplicate episode can't exist, and it's exactly what the import upserts on.
- **`robots` is a table, not a hard-coded list.** The known robots are seeded by the migration. A foreign key rejects unknown robots even if application code has a bug, and adding a robot is an INSERT, not a deploy.
- **Status history is its own append-only table, not columns on the request.** It answers "who changed it and when", and the analytics median uses it (time to *first* delivery).

### Where state lives

All state lives in PostgreSQL. The API is stateless:
- the session is a signed JWT in a cookie, and the user is re-read from the DB on every request;
- the only in-memory state is the list of open SSE connections (see §5).

### Hardest decisions

1. **Where the rules are enforced.** Each rule is checked in Python, for a clear error message, *and* enforced in the database where a race could break it:
   - `UNIQUE(assignments.episode_id)` is the real guarantee for "one request per episode". Two operators assigning the same episode at the same instant both pass the Python check, because neither has committed yet. The constraint rejects the second, and we turn that into a 409.
   - Status changes and assign/unassign take a row lock on the request (`SELECT … FOR UPDATE`). So "deliver" can't run while someone is unassigning, and the "at least N episodes" check stays true until commit.
   - `CHECK` constraints on status, quality and counts are a second line of defence.
2. **Conflicting duplicate rows in the CSV.** EP-00011 appears as `bad` and as `good`, and `ep-00003` differs from `EP-00003`. I reject **all** copies and report every line, rather than picking first or last. Guessing wrong here means delivering a bad episode as good. Identical duplicates are harmless: keep one, report the rest.
3. **Session design.** A JWT in an **HttpOnly, SameSite=Strict** cookie instead of a bearer token in localStorage. An XSS bug can't read it, the browser won't send it cross-site (CSRF), and `EventSource` (SSE) sends it automatically. The cost is no per-token revocation (see §4).

### Import rules (seed/episodes.csv)

**Policy: normalise *formatting*, never guess *values*.** Every skipped row is reported with its line number and reason.

| Case | Decision |
|---|---|
| whitespace, casing (` arm-01`, `  Pick Cup `, `USABLE`, `ep-00003`) | normalised |
| dates `2026-08-14 09:12:00`, `…Z`, `14/08/2026 09:15` | accepted. `DD/MM` is day-first, as the export shows (`14/08`). Naive times are treated as UTC |
| `not a date` | rejected |
| duration `45.5`, blank, `-5`, `0`, `N/A`, `999999` | rejected: must be whole seconds, 1 to 14,400 (4 h) |
| unknown or blank robot (`arm-99`) | rejected |
| invalid or blank quality (`excellent`) | rejected |
| blank operator name | accepted as NULL (no rule depends on it) |
| wrong column count, blank lines | rejected / reported |
| quoted comma (`"pick cup, then place"`) | kept (real CSV parser) |
| identical duplicate | first kept, others reported |
| same ID, different values | all copies rejected |

Re-import is an upsert on `episode_id` that only rewrites rows whose values changed (`IS DISTINCT FROM`, which is NULL-safe). Result on the seed file: **191 read, 171 inserted, 20 skipped**, and a re-run gives 171 unchanged. The file uses CRLF line endings, and Excel's UTF-8 BOM is handled.

### Other decisions made under ambiguity

- **A client can't see another client's request.** It returns **404**, not 403, so IDs can't be probed.
- **409 vs 403 on transitions.** 409 means the move doesn't exist from this state. 403 means it exists but belongs to another role. Admins can do everything operators can, but **not** accept or reject; that's the client's decision.
- **Assignments can only change while the request is `in_progress`.** Once delivered, the set the client is reviewing is frozen. Assigning is all-or-nothing per call. "At least `episodes_requested`" allows over-assignment (spares).
- **Analytics** filters episodes by `recorded_at` and requests by `created_at`. Days are UTC calendar days. The median is measured to the *first* delivery, so rework doesn't distort turnaround time.
- **Live updates are for staff only**, because events reveal activity on every client's requests.

## 2. Deliberately left out / next with two more days

**Left out:**
- an admin UI for users and a UI for CSV upload (both are API/CLI only);
- pagination of the request list;
- assignment history (unassigning deletes the row);
- per-token revocation and login rate limiting;
- a record of past import runs;
- unit tests for the frontend (it was verified with a scripted browser run of the full lifecycle instead).

**With two more days:**
1. **Login rate limiting**, and a `token_version` column on users, so one user's tokens can be revoked.
2. **Admin UI**: users, plus CSV upload that shows the import report.
3. **An `import_runs` table**, storing each import's report and who ran it.
4. **Keep assignment history**: soft-delete with `unassigned_at` instead of deleting the row.
5. **Daily rollup table for analytics** (see §5).
6. **React Router**, so a request has its own URL (bookmarks, back button).

## 3. Something that went wrong

**A fresh clone failed to start.** After adding the API to Docker Compose, I tested from an empty volume, as a reviewer would. The API crashed with *connection refused*, even though Compose had waited for Postgres to be "healthy".

- **Diagnosis.** I compared timestamps in the two containers' logs:
  - Postgres reported "ready" at 17:22:09;
  - the API crashed at 17:22:12;
  - Postgres logged "init process complete" only at 17:22:22.

  On a new volume, the official image first runs a **temporary init server that listens only on the Unix socket**. `pg_isready` checks the socket by default, so the healthcheck passed during init. The API connects over TCP and was refused.
- **Fix.** `pg_isready -h 127.0.0.1` makes the healthcheck test TCP, the same path the API uses. I added `restart: on-failure` as a safety net. Verified: a clean volume comes up healthy with 0 restarts.
- **Lesson.** A health check should exercise the same path as the real client. My daily dev loop never wiped the volume, so only the "fresh clone" test caught it.

**A smaller one.** The CLI import printed its JSON report *and* a JSON log line to stdout, so piping it into a parser failed with "Extra data: line 2". The root cause was the log handler writing to stdout. Logs now go to stderr, and a regression test asserts that stdout is pure JSON.

**Also caught by tests:**
- My first deliver guard used `!=` instead of `<`, which would have made over-assigned requests impossible to deliver. Now there's a test for over-assignment.
- One test passed *before* its endpoint existed, because FastAPI returns 404 for unknown routes too. It now also checks the error message.

## 4. Security

- **Passwords.**
  - bcrypt (cost 12) with a per-hash salt.
  - Seed passwords are hashed on seeding.
  - Unknown emails are still checked against a dummy hash, so response time doesn't reveal which accounts exist.
  - Passwords over bcrypt's 72-byte limit are rejected cleanly (401/422, never 500).
- **Tokens.**
  - HS256 JWT holding only the user id and expiry (8 h).
  - The secret comes from the `JWT_SECRET` env var. PyJWT flagged my first dev default as shorter than the 32 bytes HS256 needs, and I fixed it.
  - The cookie is HttpOnly and SameSite=Strict, and `Secure` is enabled via `COOKIE_SECURE` behind HTTPS.
  - The user is re-loaded on each request, so deactivation and role changes apply immediately.
- **Authorization.**
  - Enforced on the server for every endpoint (`require_roles`, the transition table, and own-requests-only filtering).
  - The UI only *displays* the server-computed `allowed_transitions`.
  - Tests call the API directly to prove hidden buttons aren't the protection.
- **Input validation.**
  - Pydantic schemas for every body and query: lengths, positive counts, deadline not in the past, enums for status, quality and role.
  - Every query uses bound parameters (no string-built SQL).
  - The CSV import treats every cell as untrusted.
  - Unreadable uploads return 400.
- **Container.** The API runs as a non-root user, and seed data is mounted read-only.

**The two vulnerabilities I'd worry about most:**
1. **Broken object-level authorization (IDOR).** In a multi-tenant system, the classic bug is a new endpoint that forgets the "is this yours?" check, letting one client read another's requests. It's mitigated by one helper (`_load_for_user`) that every single-request endpoint goes through, plus tests per role. Next step: a test that walks every route as a client.
2. **Credential attacks and session theft.** There's no login rate limiting yet, so online password guessing is possible. A stolen token stays valid until it expires, because there's no per-token revocation, only deactivating the user or rotating the secret (which logs everyone out). Fixes: rate limiting by IP and account, a `token_version` column checked on each request, and shorter tokens with refresh.

Also worth noting: if episode data is ever exported back to spreadsheets, cells starting with `=`, `+`, `-` or `@` should be escaped (CSV formula injection).

## 5. Scale

**10× users:**
- **SSE breaks first, and only once there's more than one API process.** The broker keeps subscribers in one process's memory, so an operator connected to instance A never sees events published on instance B. Fix: publish through Postgres `LISTEN/NOTIFY` (no new infrastructure) or Redis pub/sub, with each instance forwarding to its local connections.
- **Each SSE connection holds a worker connection.** The DB connection is released before streaming, by design, but uvicorn and nginx connection limits need tuning.
- **The DB pool** (SQLAlchemy defaults: 5 + 10 overflow) needs sizing, and probably PgBouncer.
- **Migrations run in the API's start script.** That needs to become a one-off deploy step once there are several replicas.

**100× episodes (taking the 200k rows I load-tested with as the baseline, that's about 20M):**
- **Analytics over long ranges** becomes full scans. Measured at 200k: 1 month is 9–18 ms index-only, 1 year is 60–90 ms seq scan; that's linear, so seconds at 100×. Fix: a daily rollup table or materialized view maintained by the import. Then partition `episodes` by month.
- **The episode list's `count(*)`** becomes slow. Switch to keyset pagination with an approximate total.
- **The importer** holds one file's cleaned rows in memory and is CPU-bound in Python (200k rows in about 69 s). For huge files: `COPY` into a staging table, then deduplicate and upsert in SQL.

## 6. AI tooling

I used **Claude Code** (Anthropic) throughout:
- **Planning.** I read the brief with it, catalogued every problem in the seed CSV, and agreed a task-by-task plan, with tests first for each task.
- **Implementation.** Most code was generated in small steps, each followed by a walkthrough I had to explain back before moving on. I wrote some pieces myself first:
  - the status-transition logic;
  - the delivery guard;
  - the top-5 analytics query.

  Review caught real problems in those pieces: the `!=` vs `<` bug, an unnecessary `try/except`, and a CTE with no `SELECT`.
- **Verification.**
  - Every feature started from a failing test.
  - I checked startup from an empty Docker volume.
  - A scripted browser run covered the full lifecycle.
  - I measured the import and analytics at 200k rows.

  The tooling surfaced the incidents in §3; the fixes and the decisions recorded here are mine to defend.
