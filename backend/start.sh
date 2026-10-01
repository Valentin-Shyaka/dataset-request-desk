#!/bin/sh
set -e
alembic upgrade head
python -m app.cli seed-users /seed/users.json
# Seed only a fresh database: re-importing on every restart would overwrite newer data from later imports.
python -m app.cli import-episodes --if-empty /seed/episodes.csv > /dev/null
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
