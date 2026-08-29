#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Shared helpers for the Slipstream deployment scripts.
#
# Sourced, not executed:
#   source "$(dirname "${BASH_SOURCE[0]}")/../linux/common.sh"
# ---------------------------------------------------------------------------

# Guard against double-sourcing, which would re-run the readonly assignments
# below and fail.
[ -n "${SLIPSTREAM_COMMON_LOADED:-}" ] && return 0
SLIPSTREAM_COMMON_LOADED=1

set -euo pipefail

# --- Output ----------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'; C_DIM=$'\033[2m'
else
  C_RESET=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_DIM=''
fi

step() { printf '%s==> %s%s\n' "$C_CYAN" "$*" "$C_RESET"; }
ok()   { printf '    %s%s%s\n' "$C_GREEN" "$*" "$C_RESET"; }
warn() { printf '    %s%s%s\n' "$C_YELLOW" "$*" "$C_RESET" >&2; }
die()  { printf '%sERROR: %s%s\n' "$C_RED" "$*" "$C_RESET" >&2; exit 1; }
note() { printf '    %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }

# --- Paths -----------------------------------------------------------------
# Resolved from this file's location so the scripts work from any cwd.
SLIPSTREAM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${SLIPSTREAM_ROOT}/backend"
FRONTEND_DIR="${SLIPSTREAM_ROOT}/frontend"
VENV_PY="${BACKEND_DIR}/.venv/bin/python"

# --- Environment detection -------------------------------------------------

require_root() {
  [ "$(id -u)" -eq 0 ] || die "this script must run as root (try: sudo $0 $*)"
}

require_not_root() {
  [ "$(id -u)" -ne 0 ] || die "do not run this script as root; it operates on your own checkout"
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64)  echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *)             echo "unsupported" ;;
  esac
}

detect_distro() {
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "${ID:-unknown}"
  else
    echo "unknown"
  fi
}

# Oracle Linux and RHEL derivatives use dnf; Debian and Ubuntu use apt.
detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then echo "apt"
  elif command -v dnf >/dev/null 2>&1; then echo "dnf"
  elif command -v yum >/dev/null 2>&1; then echo "yum"
  else echo "unknown"
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }

# --- Version checks --------------------------------------------------------

check_python() {
  local py="${1:-python3}"
  have "$py" || die "$py not found. Install Python 3.11 or newer."

  local version major minor
  version="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  major="${version%%.*}"
  minor="${version##*.}"

  if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 11 ]; }; then
    die "Python 3.11+ is required; found $version"
  fi
  ok "Python $version"
}

check_node() {
  have node || die "Node.js not found. Install Node 20 or newer."
  local major
  major="$(node --version | sed 's/^v\([0-9]*\).*/\1/')"
  [ "$major" -ge 20 ] || die "Node 20+ is required; found v$major"
  ok "Node v$major"
}

check_ffmpeg() {
  if have ffmpeg && have ffprobe; then
    ok "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"
    return 0
  fi
  # Not fatal: the app degrades honestly, reporting merged rungs and MP3
  # conversion as unavailable rather than failing mid-download.
  warn "ffmpeg/ffprobe not found — merged video rungs and MP3 conversion will be unavailable"
  return 1
}

# --- Secrets ---------------------------------------------------------------

generate_secret() {
  # python's secrets module rather than openssl or /dev/urandom + tr, because
  # it is guaranteed present (we just checked for it) and needs no encoding
  # cleanup.
  "${1:-python3}" -c 'import secrets; print(secrets.token_urlsafe(64))'
}

generate_password() {
  "${1:-python3}" - <<'PY'
import secrets
import string

alphabet = string.ascii_letters + string.digits + "-_@#%+="
print("".join(secrets.choice(alphabet) for _ in range(20)))
PY
}

# --- Health ----------------------------------------------------------------

wait_for_health() {
  local url="${1:-http://127.0.0.1:8000/api/health/ready}"
  local attempts="${2:-30}"
  local i

  for i in $(seq 1 "$attempts"); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      ok "healthy after ${i}s"
      return 0
    fi
    sleep 1
  done
  return 1
}

# --- Confirmation ----------------------------------------------------------

confirm() {
  local prompt="${1:-Continue?}"
  local expected="${2:-yes}"
  local answer

  # Non-interactive callers (CI, a cron job) must not hang on a read.
  if [ ! -t 0 ]; then
    die "$prompt requires an interactive terminal"
  fi

  printf '%s [type "%s"]: ' "$prompt" "$expected"
  read -r answer
  [ "$answer" = "$expected" ]
}
