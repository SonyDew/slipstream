#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Update a bare-metal Slipstream installation.
#
#   sudo scripts/linux/update.sh                # full update
#   sudo scripts/linux/update.sh --ytdlp-only   # just refresh the extractor
#
# Backs up first, then updates dependencies, applies migrations, rebuilds the
# frontend, and restarts.
#
# yt-dlp is the dependency that actually needs a cadence: platforms change
# their players constantly, so a months-old release stops extracting. A monthly
# run of this script is the maintenance the project needs.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/linux/common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_DIR="${INSTALL_DIR:-/opt/slipstream}"
SERVICE_USER="${SERVICE_USER:-slipstream}"
PORT="${PORT:-8000}"

YTDLP_ONLY=0
SKIP_BACKUP=0
SKIP_GIT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ytdlp-only) YTDLP_ONLY=1 ;;
    --skip-backup) SKIP_BACKUP=1 ;;
    --skip-git) SKIP_GIT=1 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

require_root
INSTALL_VENV_PY="${INSTALL_DIR}/backend/.venv/bin/python"
[ -x "$INSTALL_VENV_PY" ] || die "no installation at ${INSTALL_DIR} (set INSTALL_DIR=)"

as_service() { sudo -u "$SERVICE_USER" "$@"; }

# --- yt-dlp fast path ------------------------------------------------------
if [ "$YTDLP_ONLY" -eq 1 ]; then
  step "Updating yt-dlp"
  BEFORE="$("$INSTALL_VENV_PY" -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')"
  "$INSTALL_VENV_PY" -m pip install --upgrade yt-dlp --quiet
  AFTER="$("$INSTALL_VENV_PY" -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')"

  if [ "$BEFORE" = "$AFTER" ]; then
    ok "already current (${AFTER})"
  else
    ok "${BEFORE} -> ${AFTER}"
  fi

  # The extractor is loaded at import time, so a restart is required for the
  # new version to take effect.
  step "Restarting"
  systemctl restart slipstream.service
  wait_for_health "http://127.0.0.1:${PORT}/api/health/ready" 45 \
    || die "the service did not come back; journalctl -u slipstream -n 50"
  printf '\n'
  ok "done"
  exit 0
fi

# --- Backup ----------------------------------------------------------------
if [ "$SKIP_BACKUP" -eq 0 ]; then
  step "Backing up before the update"
  "${SCRIPT_DIR}/backup.sh" || die "backup failed; aborting the update"
else
  warn "backup skipped"
fi

# --- Source ----------------------------------------------------------------
if [ "$SKIP_GIT" -eq 0 ] && [ -d "${INSTALL_DIR}/.git" ]; then
  step "Pulling the latest source"
  # Refuse to pull over local edits rather than producing a merge conflict in
  # a directory nobody is watching.
  if ! as_service git -C "$INSTALL_DIR" diff --quiet; then
    warn "the working tree has local modifications; skipping git pull"
    note "commit, stash, or discard them, or re-run with --skip-git"
  else
    as_service git -C "$INSTALL_DIR" pull --ff-only
    ok "source updated"
  fi
fi

# --- Dependencies ----------------------------------------------------------
step "Refreshing Python dependencies"
"$INSTALL_VENV_PY" -m pip install --upgrade pip --quiet
"$INSTALL_VENV_PY" -m pip install -r "${INSTALL_DIR}/backend/requirements.txt" --quiet
"$INSTALL_VENV_PY" -m pip install --upgrade yt-dlp --quiet
ok "done ($("$INSTALL_VENV_PY" -m pip show yt-dlp | awk '/^Version:/{print "yt-dlp " $2}'))"

# --- Migrations ------------------------------------------------------------
step "Applying database migrations"
if as_service env -C "${INSTALL_DIR}/backend" "$INSTALL_VENV_PY" -m alembic upgrade head; then
  ok "schema current"
else
  warn "alembic upgrade failed"
  note "the app also creates missing tables on boot, but read the output above"
  note "before assuming the schema is correct"
fi

# --- Frontend --------------------------------------------------------------
step "Rebuilding the frontend"
if have npm; then
  # Build into a temporary directory and swap it in, so a failed build leaves
  # the working bundle serving instead of an empty dist.
  pushd "${INSTALL_DIR}/frontend" >/dev/null
  if [ -f package-lock.json ]; then as_service npm ci --silent; else as_service npm install --silent; fi
  if as_service npm run build; then
    ok "dist rebuilt"
  else
    warn "the frontend build failed; the previous dist is still in place"
  fi
  popd >/dev/null
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/frontend"
else
  warn "npm is unavailable; the existing dist is unchanged"
fi

# --- Restart ---------------------------------------------------------------
step "Restarting"
systemctl restart slipstream.service

if wait_for_health "http://127.0.0.1:${PORT}/api/health/ready" 45; then
  as_service env -C "${INSTALL_DIR}/backend" "$INSTALL_VENV_PY" -m app.cli verify || true
else
  warn "the service did not report ready within 45s"
  note "journalctl -u slipstream -n 50 --no-pager"
  note "roll back with: sudo scripts/linux/restore.sh ${INSTALL_DIR}/backups/<latest>.tar.gz"
  exit 1
fi

printf '\n'
step "Update complete"
printf '\n'
