#!/bin/sh
set -e
alembic upgrade head
python -m app.cli seed-users /seed/users.json
# Safe on every start: the import is idempotent (a second run reports everything as unchanged).
python -m app.cli import-episodes /seed/episodes.csv > /dev/null
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
