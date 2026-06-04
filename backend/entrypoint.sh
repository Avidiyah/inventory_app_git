#!/usr/bin/env sh
# Container entrypoint: bring the schema up to date, then hand off to
# uvicorn.
#
# `alembic upgrade head` is idempotent, so it is safe on every cold
# start (Render's free tier spins the service down when idle and back
# up on the next request). On the very first deploy it creates the
# empty schema; your existing data is loaded once, separately, via
# scripts/import_local_data.ps1 (see docs/deploy-render.md).
#
# Migrations on a single free instance cannot race; revisit if you ever
# scale to multiple instances.
set -e

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> starting uvicorn on port ${PORT:-8124}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8124}"
