# Decisions & incidents log (scratch — becomes NOTES.md)

## Import (seed/episodes.csv)
- Policy: normalise *formatting*, never guess *values*. Rows needing a guess are skipped with line + reason.
- Normalised: whitespace, casing (task lowercased, IDs uppercased, robot lowercased), quality casing.
- Dates: ISO (T or space, optional Z) + DD/MM/YYYY HH:MM (day-first, as the export uses). Naive times = UTC.
- duration_seconds: whole seconds 1..14400 (4h). Rejected: 45.5, blank, -5, 0, N/A, 999999.
- Blank operator_name -> NULL (no rule depends on it).
- Unknown/blank robot rejected (robots table = FK).
- Identical duplicate rows: keep first, report the rest.
- Same episode_id with different values (EP-00011 good/bad; EP-00003 vs ep-00003): reject ALL copies — we can't know which is right.
- Seed file uses CRLF line endings; csv module + newline="" handles it. Excel BOM handled via utf-8-sig.
- Re-import = upsert on episode_id; rows only rewritten if a value actually changed (IS DISTINCT FROM).
- Result: 191 read, 171 inserted, 20 skipped; rerun: 171 unchanged.

## Auth
- JWT in HttpOnly + SameSite=Strict cookie; user re-read from DB each request (deactivation/role change immediate).
- PyJWT warned the dev secret was < 32 bytes (RFC 7518) -> lengthened; prod secret comes from env.
- Known gap: no single-token revocation (would add token_version column or session table).

## Incidents (for NOTES §3)
- CLI import output wasn't valid JSON: log lines and the report both went to stdout, so piping to jq/json.load failed
  ("Extra data: line 2"). Diagnosed by looking at raw stdout; root cause StreamHandler(sys.stdout). Fix: logs -> stderr.
  Regression test: test_cli_prints_only_the_report_on_stdout.
- Fresh-clone `docker compose up` failed: api crashed with "connection refused" even though db was "healthy".
  Diagnosed by comparing db and api log timestamps: on an empty volume the postgres image runs a temporary
  init server on the Unix socket only; `pg_isready` (socket by default) reported healthy during init, the api
  connected over TCP and was refused. Fix: healthcheck `pg_isready -h 127.0.0.1` (TCP), plus `restart: on-failure`
  on api as a safety net. Verified: clean volume -> healthy with 0 restarts. Lesson: health checks must test the
  same path the client uses.

## Ops
- Migrations + seed + import run in api start.sh; all idempotent so restarts are safe. With several replicas,
  migrations should move to a one-off job before deploy.
- Tests run inside the api image (`make test`) against drd_test; pytest cache disabled (container is non-root).
