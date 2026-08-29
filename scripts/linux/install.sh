#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bare-metal (non-Docker) installer for Slipstream on a Linux host.
#
#   sudo scripts/linux/install.sh
#
# Creates a system user, installs into /opt/slipstream, writes a .env with a
# generated SECRET_KEY, installs the systemd unit, and starts it. nginx and TLS
# are handled separately — see scripts/ubuntu/ or scripts/oracle/.
#
# Idempotent: re-running upgrades in place without touching an existing .env
# or database.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/linux/common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_DIR="${INSTALL_DIR:-/opt/slipstream}"
SERVICE_USER="${SERVICE_USER:-slipstream}"
PORT="${PORT:-8000}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"

require_root "$@"

ARCH="$(detect_arch)"
DISTRO="$(detect_distro)"
PKG="$(detect_pkg_manager)"

printf '\n'
step "Slipstream installer"
note "distro: ${DISTRO}   arch: ${ARCH}   target: ${INSTALL_DIR}"
printf '\n'

[ "$ARCH" = "unsupported" ] && die "unsupported architecture: $(uname -m) (need x86_64 or aarch64)"
[ "$PKG" = "unknown" ] && die "no supported package manager found (apt, dnf, or yum)"

# --- System packages -------------------------------------------------------
step "Installing system packages"

case "$PKG" in
  apt)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
      python3 python3-venv python3-dev \
      build-essential libffi-dev \
      ffmpeg curl ca-certificates git
    ;;
  dnf|yum)
    # Oracle Linux and RHEL do not ship ffmpeg in the base repos; it comes from
    # RPM Fusion, which needs EPEL first.
    "$PKG" install -y -q python3 python3-devel gcc gcc-c++ make libffi-devel \
                         curl ca-certificates git
    if ! have ffmpeg; then
      warn "ffmpeg is not in the base repositories on ${DISTRO}"
      note "enabling EPEL and RPM Fusion"
      "$PKG" install -y -q oracle-epel-release-el9 2>/dev/null \
        || "$PKG" install -y -q epel-release 2>/dev/null \
        || warn "could not enable EPEL automatically"
      "$PKG" install -y -q --nogpgcheck \
        "https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-9.noarch.rpm" \
        2>/dev/null || warn "could not enable RPM Fusion automatically"
      "$PKG" install -y -q ffmpeg ffmpeg-devel 2>/dev/null \
        || warn "ffmpeg install failed; see docs/ORACLE.md for a static build"
    fi
    ;;
esac
ok "system packages ready"

check_python python3
check_ffmpeg || true

# Node is needed only to build the SPA. If the checkout already has a built
# dist (a release tarball, or a build on another machine), skip the toolchain.
NEED_NODE=1
if [ -f "${SLIPSTREAM_ROOT}/frontend/dist/index.html" ]; then
  NEED_NODE=0
  ok "frontend/dist is already built; skipping Node"
fi

if [ "$NEED_NODE" -eq 1 ]; then
  step "Installing Node.js"
  if have node && [ "$(node --version | sed 's/^v\([0-9]*\).*/\1/')" -ge 20 ]; then
    check_node
  else
    case "$PKG" in
      apt)
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1
        apt-get install -y -qq nodejs
        ;;
      dnf|yum)
        "$PKG" module reset -y -q nodejs 2>/dev/null || true
        "$PKG" module enable -y -q nodejs:20 2>/dev/null || true
        "$PKG" install -y -q nodejs
        ;;
    esac
    check_node
  fi
fi

# --- Service user ----------------------------------------------------------
step "Creating the service user"

if id "$SERVICE_USER" >/dev/null 2>&1; then
  ok "user ${SERVICE_USER} already exists"
else
  # System account: no login shell, no home in /home, cannot be used to log in.
  useradd --system --create-home --home-dir "$INSTALL_DIR" \
          --shell /usr/sbin/nologin "$SERVICE_USER" 2>/dev/null \
    || useradd --system --create-home --home-dir "$INSTALL_DIR" \
               --shell /sbin/nologin "$SERVICE_USER"
  ok "created ${SERVICE_USER}"
fi

# --- Copy the application --------------------------------------------------
step "Installing to ${INSTALL_DIR}"

mkdir -p "$INSTALL_DIR"

if [ "$SLIPSTREAM_ROOT" != "$INSTALL_DIR" ]; then
  # --delete keeps the target clean across upgrades, but data/ and .venv/ must
  # survive: one is the database, the other is expensive to rebuild.
  if have rsync; then
    rsync -a --delete \
      --exclude='.git/' --exclude='data/' --exclude='.venv/' \
      --exclude='node_modules/' --exclude='__pycache__/' \
      --exclude='.env' --exclude='backups/' \
      "${SLIPSTREAM_ROOT}/" "${INSTALL_DIR}/"
  else
    cp -r "${SLIPSTREAM_ROOT}/backend" "${SLIPSTREAM_ROOT}/frontend" \
          "${SLIPSTREAM_ROOT}/scripts" "${SLIPSTREAM_ROOT}/deploy" \
          "${SLIPSTREAM_ROOT}/nginx" "$INSTALL_DIR/" 2>/dev/null || true
  fi
  ok "application files copied"
else
  ok "already installed in place"
fi

mkdir -p "${INSTALL_DIR}/data/db" "${INSTALL_DIR}/data/logs" "${INSTALL_DIR}/data/temp"

# --- Python environment ----------------------------------------------------
step "Building the Python environment"

INSTALL_VENV_PY="${INSTALL_DIR}/backend/.venv/bin/python"

if [ ! -x "$INSTALL_VENV_PY" ]; then
  python3 -m venv "${INSTALL_DIR}/backend/.venv"
  ok "virtualenv created"
fi

"$INSTALL_VENV_PY" -m pip install --upgrade pip setuptools wheel --quiet
"$INSTALL_VENV_PY" -m pip install -r "${INSTALL_DIR}/backend/requirements.txt" --quiet
ok "dependencies installed"

# --- Frontend --------------------------------------------------------------
if [ ! -f "${INSTALL_DIR}/frontend/dist/index.html" ]; then
  step "Building the frontend"
  pushd "${INSTALL_DIR}/frontend" >/dev/null
  if [ -f package-lock.json ]; then npm ci --silent; else npm install --silent; fi
  npm run build
  popd >/dev/null
  [ -f "${INSTALL_DIR}/frontend/dist/index.html" ] || die "the build finished but dist/index.html is missing"
  ok "frontend built"
else
  ok "frontend already built"
fi

# --- Configuration ---------------------------------------------------------
step "Writing configuration"

ENV_FILE="${INSTALL_DIR}/.env"

if [ -f "$ENV_FILE" ]; then
  ok ".env already exists; leaving it untouched"
  ADMIN_PASSWORD=""
else
  SECRET="$(generate_secret python3)"
  ADMIN_PASSWORD="$(generate_password python3)"

  cat > "$ENV_FILE" <<EOF
# Generated by scripts/linux/install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains credentials. Keep it at mode 600 and out of version control.

ENVIRONMENT=production
SECRET_KEY=${SECRET}

APP_URL=http://localhost:${PORT}
DOMAIN=localhost

# Set COOKIE_SECURE=true and TRUSTED_PROXY_COUNT=1 once nginx terminates TLS
# in front of this instance. Until then the app is loopback-only.
COOKIE_SECURE=false
TRUSTED_PROXY_COUNT=0

INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_EMAIL=admin@localhost
INITIAL_ADMIN_PASSWORD=${ADMIN_PASSWORD}

DATA_DIR=${INSTALL_DIR}/data
MAX_CONCURRENT_DOWNLOADS=2
LOG_JSON=true
EOF
  ok ".env written with a generated SECRET_KEY"
fi

# 600 before the chown so the file is never briefly world-readable.
chmod 600 "$ENV_FILE"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
ok "ownership set to ${SERVICE_USER}"

# --- systemd ---------------------------------------------------------------
step "Installing the systemd unit"

UNIT_TEMPLATE="${INSTALL_DIR}/deploy/linux/systemd/slipstream.service"
[ -f "$UNIT_TEMPLATE" ] || die "unit template not found at ${UNIT_TEMPLATE}"

# The template carries placeholders rather than hardcoded paths so INSTALL_DIR
# and SERVICE_USER can be overridden.
sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
    -e "s|@SERVICE_USER@|${SERVICE_USER}|g" \
    -e "s|@BIND_HOST@|${BIND_HOST}|g" \
    -e "s|@PORT@|${PORT}|g" \
    "$UNIT_TEMPLATE" > /etc/systemd/system/slipstream.service

systemctl daemon-reload
systemctl enable slipstream.service >/dev/null 2>&1
ok "slipstream.service installed and enabled"

# The backup and yt-dlp timers are installed but left disabled: an unattended
# job that restarts the app or writes to disk on a schedule should be an
# explicit choice, not a side effect of installing.
UNIT_DIR="${INSTALL_DIR}/deploy/linux/systemd"
for unit in slipstream-backup.service slipstream-backup.timer \
            slipstream-ytdlp-update.service slipstream-ytdlp-update.timer; do
  [ -f "${UNIT_DIR}/${unit}" ] || continue
  sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
      -e "s|@SERVICE_USER@|${SERVICE_USER}|g" \
      "${UNIT_DIR}/${unit}" > "/etc/systemd/system/${unit}"
done
systemctl daemon-reload
ok "backup and yt-dlp timers installed (disabled; see below)"

# --- SELinux ---------------------------------------------------------------
# Oracle Linux enforces SELinux by default, and a service running out of /opt
# is denied network binding and file writes without this.
if have getenforce && [ "$(getenforce)" = "Enforcing" ]; then
  step "Configuring SELinux"
  if have semanage; then
    semanage fcontext -a -t bin_t "${INSTALL_DIR}/backend/.venv/bin(/.*)?" 2>/dev/null || true
    restorecon -R "${INSTALL_DIR}/backend/.venv/bin" 2>/dev/null || true
    ok "labelled the virtualenv binaries"
  else
    warn "SELinux is enforcing but semanage is unavailable"
    note "install policycoreutils-python-utils, or see docs/ORACLE.md"
  fi
fi

# --- Start -----------------------------------------------------------------
step "Starting Slipstream"

systemctl restart slipstream.service

if wait_for_health "http://127.0.0.1:${PORT}/api/health/ready" 45; then
  sudo -u "$SERVICE_USER" env -C "${INSTALL_DIR}/backend" \
    "$INSTALL_VENV_PY" -m app.cli verify || true
else
  warn "the service did not report ready within 45s"
  note "journalctl -u slipstream -n 50 --no-pager"
  exit 1
fi

printf '\n'
step "Installed"
printf '\n'
note "URL:      http://127.0.0.1:${PORT}"
note "Service:  systemctl {status,restart,stop} slipstream"
note "Logs:     journalctl -u slipstream -f"
note "Config:   ${ENV_FILE}"
printf '\n'
note "Recommended, both off by default:"
note "  systemctl enable --now slipstream-backup.timer         nightly backup"
note "  systemctl enable --now slipstream-ytdlp-update.timer   monthly yt-dlp refresh"
printf '\n'

if [ -n "$ADMIN_PASSWORD" ]; then
  printf '  %sInitial admin credentials%s\n' "$C_YELLOW" "$C_RESET"
  printf '    username: admin\n'
  printf '    password: %s\n' "$ADMIN_PASSWORD"
  printf '  %sChange this after signing in. The account cannot alter settings until you do.%s\n' \
    "$C_YELLOW" "$C_RESET"
  printf '\n'
fi

note "The app is bound to ${BIND_HOST} and has no TLS."
note "For a public deployment, add nginx and a certificate:"
note "  sudo scripts/ubuntu/deploy.sh --domain example.com --email you@example.com"
note "  sudo scripts/oracle/deploy.sh --domain example.com --email you@example.com"
printf '\n'
