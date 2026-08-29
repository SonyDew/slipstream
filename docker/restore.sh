#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Restore a Slipstream data volume from a backup archive.
#
#   docker/restore.sh backups/slipstream-20260825T120000Z.tar.gz
#
# This REPLACES the current database and logs. The app is stopped first,
# because writing under a live SQLite connection corrupts it.
# ---------------------------------------------------------------------------
set -euo pipefail

ARCHIVE="${1:?usage: docker/restore.sh <archive.tar.gz>}"
CONTAINER="${CONTAINER:-slipstream}"
VOLUME="${VOLUME:-slipstream-data}"

if [ ! -f "$ARCHIVE" ]; then
  echo "no such archive: $ARCHIVE" >&2
  exit 1
fi

if ! tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
  echo "$ARCHIVE is not a readable gzip archive" >&2
  exit 1
fi

if ! tar -tzf "$ARCHIVE" | grep -q 'db/slipstream.backup.db'; then
  echo "$ARCHIVE does not contain db/slipstream.backup.db." >&2
  echo "It was not produced by docker/backup.sh; restoring it would leave the" >&2
  echo "instance without a database. Aborting." >&2
  exit 1
fi

echo "This will REPLACE the contents of volume '${VOLUME}'."
echo "Archive: ${ARCHIVE}"
printf 'Type "restore" to continue: '
read -r CONFIRM
[ "$CONFIRM" = "restore" ] || { echo "aborted"; exit 1; }

if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "==> stopping $CONTAINER"
  docker stop "$CONTAINER" >/dev/null
  RESTART=1
else
  RESTART=0
fi

echo "==> restoring into $VOLUME"
# A throwaway container is the only way to write to a named volume while the
# app container is down. The old tree is cleared first so files that no longer
# exist in the backup do not survive the restore.
docker run --rm -i \
  -v "${VOLUME}:/data" \
  -w /data \
  alpine:3.20 sh -c '
    set -e
    find /data -mindepth 1 -delete
    tar -xzf - -C /data
    # backup.sh stores the online snapshot under a different name so it can
    # coexist with the live database; put it back as the real one.
    if [ -f /data/db/slipstream.backup.db ]; then
      mv /data/db/slipstream.backup.db /data/db/slipstream.db
    fi
    # A restored database must not inherit a stale write-ahead log.
    rm -f /data/db/slipstream.db-wal /data/db/slipstream.db-shm
    mkdir -p /data/db /data/logs /data/temp
    chown -R 10001:10001 /data
  ' < "$ARCHIVE"

if [ "$RESTART" -eq 1 ]; then
  echo "==> starting $CONTAINER"
  docker start "$CONTAINER" >/dev/null
  echo "==> waiting for health"
  for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" curl -fsS http://127.0.0.1:8000/api/health/ready >/dev/null 2>&1; then
      echo "==> healthy"
      exit 0
    fi
    sleep 2
  done
  echo "WARNING: the container did not report ready within 60s." >&2
  echo "Check: docker logs $CONTAINER" >&2
  exit 1
fi

echo "==> restored. Start the stack with: docker compose up -d"
