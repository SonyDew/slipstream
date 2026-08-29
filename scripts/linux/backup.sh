#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Back up a bare-metal Slipstream installation.
#
#   sudo scripts/linux/backup.sh
#   sudo scripts/linux/backup.sh /mnt/backups
#   KEEP=30 sudo scripts/linux/backup.sh
#
# Uses SQLite's online backup API rather than copying files. In WAL mode the
# .db, -wal, and -shm files are only consistent together, so a plain copy of
# the .db while the app is writing can restore to a corrupt state.
#
# Safe to run against a live instance; no downtime.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/linux/common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_DIR="${INSTALL_DIR:-/opt/slipstream}"
DEST="${1:-${INSTALL_DIR}/backups}"
KEEP="${KEEP:-7}"

INSTALL_VENV_PY="${INSTALL_DIR}/backend/.venv/bin/python"
DATA_DIR="${INSTALL_DIR}/data"
DB_PATH="${DATA_DIR}/db/slipstream.db"

[ -x "$INSTALL_VENV_PY" ] || die "no installation at ${INSTALL_DIR} (set INSTALL_DIR=)"

if [ ! -f "$DB_PATH" ]; then
  warn "no database at ${DB_PATH}; nothing to back up"
  exit 0
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${DEST}/slipstream-${STAMP}.tar.gz"
STAGING="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${STAGING}'" EXIT

mkdir -p "$DEST"

step "Backing up to ${ARCHIVE}"

mkdir -p "${STAGING}/db"
DB_PATH="$DB_PATH" SNAPSHOT="${STAGING}/db/slipstream.db" \
"$INSTALL_VENV_PY" - <<'PY'
import os
import sqlite3

src = sqlite3.connect(f"file:{os.environ['DB_PATH']}?mode=ro", uri=True)
dst = sqlite3.connect(os.environ["SNAPSHOT"])
with dst:
    src.backup(dst)
dst.close()
src.close()
PY
ok "database snapshot taken"

if [ -d "${DATA_DIR}/logs" ]; then
  cp -r "${DATA_DIR}/logs" "${STAGING}/logs"
  ok "logs included"
fi

# SECRET_KEY lives here. Losing it invalidates every session, and losing it
# alongside the database means the instance cannot be restored intact.
if [ -f "${INSTALL_DIR}/.env" ]; then
  cp "${INSTALL_DIR}/.env" "${STAGING}/env.backup"
  ok ".env included (contains SECRET_KEY and credentials)"
fi

# data/temp is skipped: in-flight downloads are worthless after a restore.
tar -czf "$ARCHIVE" -C "$STAGING" .
chmod 600 "$ARCHIVE"

SIZE="$(du -h "$ARCHIVE" | cut -f1)"
ok "wrote ${ARCHIVE} (${SIZE}, mode 600)"

if [ "$KEEP" -gt 0 ]; then
  # -print0/xargs -0 rather than a glob loop, so filenames with spaces in a
  # custom destination do not break the prune.
  mapfile -t OLD < <(find "$DEST" -maxdepth 1 -name 'slipstream-*.tar.gz' -printf '%T@ %p\n' \
                     | sort -rn | tail -n "+$((KEEP + 1))" | cut -d' ' -f2-)
  for f in "${OLD[@]:-}"; do
    [ -n "$f" ] || continue
    rm -f "$f"
    note "pruned $(basename "$f")"
  done
fi

printf '\n'
warn "This archive contains password hashes, session records, and SECRET_KEY."
note "Store it as securely as the instance itself."
note "Restore with: sudo scripts/linux/restore.sh ${ARCHIVE}"
printf '\n'
