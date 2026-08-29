#!/bin/sh
# ---------------------------------------------------------------------------
# Slipstream container entrypoint.
#
# Usage (as the container command):
#   serve            start uvicorn (default)
#   verify           run the operational verify check and exit
#   cli <args...>    run `python -m app.cli <args...>`
#   <anything else>  executed verbatim
# ---------------------------------------------------------------------------
set -eu

log() { printf '[entrypoint] %s\n' "$*"; }

: "${PORT:=8000}"
: "${HOST:=0.0.0.0}"
: "${WEB_CONCURRENCY:=1}"
: "${DATA_DIR:=/app/data}"

cd /app/backend

# The image creates these, but a bind mount replaces the directory wholesale,
# so they have to be re-created at start.
mkdir -p "${DATA_DIR}/db" "${DATA_DIR}/logs" "${DATA_DIR}/temp"

if [ ! -w "${DATA_DIR}" ]; then
  log "FATAL: ${DATA_DIR} is not writable by uid $(id -u)."
  log "A bind-mounted host directory must be owned by uid 10001, or use a named volume."
  exit 1
fi

case "${1:-serve}" in
  serve)
    if [ "${ENVIRONMENT:-production}" = "production" ] && [ -z "${SECRET_KEY:-}" ]; then
      log "FATAL: SECRET_KEY is required when ENVIRONMENT=production."
      log "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
      exit 1
    fi

    if [ ! -f /app/frontend/dist/index.html ]; then
      log "WARNING: no SPA bundle at /app/frontend/dist — only /api will respond."
    fi

    # More than one worker would give each process its own in-memory job queue
    # and its own cleanup loop, so a job submitted to worker A is invisible to
    # worker B. Scale by raising MAX_CONCURRENT_DOWNLOADS, not WEB_CONCURRENCY.
    if [ "${WEB_CONCURRENCY}" != "1" ]; then
      log "WARNING: WEB_CONCURRENCY=${WEB_CONCURRENCY}; the job queue is per-process."
      log "         Jobs will appear to vanish between requests. Forcing 1 worker."
      WEB_CONCURRENCY=1
    fi

    log "Slipstream starting on ${HOST}:${PORT} (env=${ENVIRONMENT:-production})"
    # FORWARDED_ALLOW_IPS defaults to * because the proxy sits on a container
    # network whose address is not predictable. That only makes uvicorn parse
    # the forwarded headers; how far the app trusts them for rate limiting is
    # governed separately by TRUSTED_PROXY_COUNT, which must match the real
    # proxy depth. If the container port is published directly to the internet
    # without a proxy, set FORWARDED_ALLOW_IPS to an empty value.
    exec python -m uvicorn app.main:app \
      --host "${HOST}" \
      --port "${PORT}" \
      --workers "${WEB_CONCURRENCY}" \
      --proxy-headers \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
      --timeout-keep-alive 75 \
      --no-server-header
    ;;

  verify)
    exec python -m app.cli verify
    ;;

  cli)
    shift
    exec python -m app.cli "$@"
    ;;

  *)
    exec "$@"
    ;;
esac
