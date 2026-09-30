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
