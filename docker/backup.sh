#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Back up a running Slipstream instance's data volume.
#
#   docker/backup.sh                 # writes ./backups/slipstream-<ts>.tar.gz
#   docker/backup.sh /mnt/backups
#
# SQLite in WAL mode cannot be copied safely with `cp` while the app is
# writing: the .db, -wal, and -shm files are only consistent together. This
# script uses `sqlite3 .backup`, which takes a proper online snapshot, then
# archives the rest of the data tree around it.
# ---------------------------------------------------------------------------
set -euo pipefail

DEST="${1:-./backups}"
CONTAINER="${CONTAINER:-slipstream}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="slipstream-${STAMP}.tar.gz"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "container '$CONTAINER' not found; set CONTAINER=<name>" >&2
  exit 1
fi

mkdir -p "$DEST"

echo "==> snapshotting the database inside $CONTAINER"
# Python's sqlite3 module is already in the image, so no extra package is
# needed. backup() is the same online-snapshot API the sqlite3 CLI uses.
docker exec "$CONTAINER" python - <<'PY'
import os
import sqlite3

data_dir = os.environ.get("DATA_DIR", "/app/data")
src_path = os.path.join(data_dir, "db", "slipstream.db")
dst_path = os.path.join(data_dir, "db", "slipstream.backup.db")

src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
dst = sqlite3.connect(dst_path)
with dst:
    src.backup(dst)
dst.close()
src.close()
print(f"snapshot written to {dst_path}")
PY

echo "==> archiving the data tree"
# Excludes the live database files: the consistent snapshot above replaces
# them, and including a mid-write .db would produce a backup that restores to
# a corrupt state. temp/ is in-flight downloads, which are worthless later.
docker exec "$CONTAINER" tar \
  --exclude='./db/slipstream.db' \
  --exclude='./db/slipstream.db-wal' \
  --exclude='./db/slipstream.db-shm' \
  --exclude='./temp/*' \
  -czf - -C /app/data . > "${DEST}/${ARCHIVE}"

docker exec "$CONTAINER" rm -f /app/data/db/slipstream.backup.db

SIZE="$(du -h "${DEST}/${ARCHIVE}" | cut -f1)"
echo "==> wrote ${DEST}/${ARCHIVE} (${SIZE})"
echo
echo "The archive contains password hashes and session records. Store it with"
echo "the same care as the instance itself."
echo "Restore with: docker/restore.sh ${DEST}/${ARCHIVE}"
