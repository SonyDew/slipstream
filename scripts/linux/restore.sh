#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Restore a bare-metal Slipstream installation from a backup archive.
#
#   sudo scripts/linux/restore.sh /opt/slipstream/backups/slipstream-<ts>.tar.gz
#
# REPLACES the current database and logs. The service is stopped first, because
# writing under a live SQLite connection corrupts it.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/linux/common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_DIR="${INSTALL_DIR:-/opt/slipstream}"
SERVICE_USER="${SERVICE_USER:-slipstream}"
ARCHIVE="${1:-}"

require_root "$@"
[ -n "$ARCHIVE" ] || die "usage: $0 <archive.tar.gz>"
[ -f "$ARCHIVE" ] || die "no such archive: ${ARCHIVE}"

tar -tzf "$ARCHIVE" >/dev/null 2>&1 || die "${ARCHIVE} is not a readable gzip archive"

# Refuse an archive that is not one of ours rather than wiping the data
# directory and leaving the instance with no database.
if ! tar -tzf "$ARCHIVE" | grep -q './db/slipstream.db'; then
  die "${ARCHIVE} contains no db/slipstream.db; it was not produced by backup.sh"
fi

DATA_DIR="${INSTALL_DIR}/data"

printf '\n'
warn "This will REPLACE the database and logs in ${DATA_DIR}."
note "Archive: ${ARCHIVE}"
printf '\n'
confirm 'Continue?' 'restore' || die "aborted"

RESTART=0
if systemctl is-active --quiet slipstream.service; then
  step "Stopping slipstream.service"
  systemctl stop slipstream.service
  RESTART=1
  ok "stopped"
fi

# The current tree is moved aside rather than deleted, so a failed restore is
# recoverable without going back to a second backup.
if [ -d "$DATA_DIR" ]; then
  ASIDE="${DATA_DIR}.pre-restore.$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$DATA_DIR" "$ASIDE"
  ok "previous data moved to ${ASIDE}"
fi

step "Restoring"
mkdir -p "$DATA_DIR"
tar -xzf "$ARCHIVE" -C "$DATA_DIR"

# A restored database must not inherit a stale write-ahead log from whatever
# was there before.
rm -f "${DATA_DIR}/db/slipstream.db-wal" "${DATA_DIR}/db/slipstream.db-shm"
mkdir -p "${DATA_DIR}/db" "${DATA_DIR}/logs" "${DATA_DIR}/temp"

# env.backup is restored alongside, not over the live .env: SECRET_KEY and the
# database have to match, but silently replacing the running configuration
# would be a surprise. The operator decides.
if [ -f "${DATA_DIR}/env.backup" ]; then
  mv "${DATA_DIR}/env.backup" "${INSTALL_DIR}/.env.restored"
  chmod 600 "${INSTALL_DIR}/.env.restored"
  warn "the archive's .env was written to ${INSTALL_DIR}/.env.restored"
  note "if SECRET_KEY differs from the live .env, every restored session is invalid;"
  note "compare them and copy it over if you want the old sessions to work."
fi

chown -R "${SERVICE_USER}:${SERVICE_USER}" "$DATA_DIR"
ok "restored and ownership set"

step "Checking the restored database"
if sudo -u "$SERVICE_USER" "${INSTALL_DIR}/backend/.venv/bin/python" -c "
import sqlite3, sys
c = sqlite3.connect('${DATA_DIR}/db/slipstream.db')
result = c.execute('PRAGMA integrity_check').fetchone()[0]
c.close()
print(result)
sys.exit(0 if result == 'ok' else 1)
"; then
  ok "integrity check passed"
else
  die "the restored database failed its integrity check; the previous data is still at ${ASIDE:-<none>}"
fi

if [ "$RESTART" -eq 1 ]; then
  step "Starting slipstream.service"
  systemctl start slipstream.service
  if wait_for_health "http://127.0.0.1:${PORT:-8000}/api/health/ready" 45; then
    ok "running"
  else
    warn "the service did not report ready within 45s"
    note "journalctl -u slipstream -n 50 --no-pager"
    exit 1
  fi
fi

printf '\n'
step "Restore complete"
note "The previous data directory was kept at ${ASIDE:-<none>}; delete it once satisfied."
printf '\n'
