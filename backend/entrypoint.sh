#!/usr/bin/env sh
# Container entrypoint: bring the schema up to date, then hand off to
# uvicorn.
#
# `alembic upgrade head` is idempotent, so it is safe on every cold
# start (Render's free tier spins the service down when idle and back
# up on the next request). On the very first deploy it creates the
# empty schema; your existing data is loaded once, separately, via
# scripts/import_local_data.ps1 (see docs/current-state.md).
#
# Migrations on a single free instance cannot race; revisit if you ever
# scale to multiple instances.
set -e

echo "==> alembic upgrade head"
alembic upgrade head

# --proxy-headers makes uvicorn resolve X-Forwarded-For into
# request.client, so the login throttle keys on the real client address
# instead of Render's proxy. --forwarded-allow-ips='*' trusts that
# header unconditionally, which is safe *here specifically* because the
# container is only reachable through Render's proxy -- never expose
# this port directly with that setting.
#
# WebSocket transport policy is explicit here as well. The protocol layer
# rejects frames above the same 64 KiB ceiling enforced by the application
# receive loop, and native ping/pong detects vanished peers without inventing
# an application-level JSON heartbeat vocabulary.
echo "==> starting uvicorn on port ${PORT:-8124}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8124}" \
    --proxy-headers --forwarded-allow-ips='*' \
    --ws-max-size 65536 --ws-ping-interval 30 --ws-ping-timeout 30
