#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Ubuntu x86_64 VPS deployment for Slipstream.
#
#   sudo scripts/ubuntu/deploy.sh --domain slipstream.example.com --email you@example.com
#
# Runs the bare-metal installer, then nginx with a Let's Encrypt certificate,
# and hardens the firewall. Use --no-tls for an internal deployment with no
# public hostname.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/linux/common.sh
source "${SCRIPT_DIR}/../linux/common.sh"

DOMAIN=""
EMAIL=""
USE_TLS=1
PORT="${PORT:-8000}"
INSTALL_DIR="${INSTALL_DIR:-/opt/slipstream}"

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:?--domain needs a value}"; shift ;;
    --email)  EMAIL="${2:?--email needs a value}"; shift ;;
    --no-tls) USE_TLS=0 ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

require_root

DISTRO="$(detect_distro)"
case "$DISTRO" in
  ubuntu|debian) ok "detected ${DISTRO}" ;;
  *) warn "this script targets Ubuntu/Debian; found '${DISTRO}'"
     confirm 'Continue anyway?' 'yes' || die "aborted" ;;
esac

if [ "$USE_TLS" -eq 1 ]; then
  [ -n "$DOMAIN" ] || die "--domain is required (or pass --no-tls)"
  [ -n "$EMAIL" ]  || die "--email is required for Let's Encrypt registration"

  # A certificate request against a hostname that does not resolve here fails
  # the http-01 challenge, so check before spending a rate-limit attempt.
  step "Checking DNS for ${DOMAIN}"
  RESOLVED="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
  PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo '')"

  if [ -z "$RESOLVED" ]; then
    die "${DOMAIN} does not resolve. Point an A record at this host first."
  elif [ -n "$PUBLIC_IP" ] && [ "$RESOLVED" != "$PUBLIC_IP" ]; then
    warn "${DOMAIN} resolves to ${RESOLVED}, but this host appears to be ${PUBLIC_IP}"
    note "if you are behind a proxy or CDN this is expected"
    confirm 'Continue?' 'yes' || die "aborted"
  else
    ok "${DOMAIN} -> ${RESOLVED}"
  fi
else
  DOMAIN="${DOMAIN:-_}"
fi

# --- Application -----------------------------------------------------------
step "Installing the application"
# Loopback bind: nginx is the only ingress, so the app must not be reachable
# directly on a public interface.
BIND_HOST=127.0.0.1 PORT="$PORT" INSTALL_DIR="$INSTALL_DIR" \
  "${SCRIPT_DIR}/../linux/install.sh"

# --- nginx -----------------------------------------------------------------
step "Installing nginx"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq nginx
ok "nginx installed"

if [ "$USE_TLS" -eq 1 ]; then
  step "Obtaining a certificate"
  apt-get install -y -qq certbot python3-certbot-nginx

  mkdir -p /var/www/acme-challenge
  chown -R www-data:www-data /var/www/acme-challenge

  # Temporary HTTP-only server block so the http-01 challenge can be served
  # before a certificate exists. The real config replaces it below.
  cat > /etc/nginx/sites-available/slipstream <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/acme-challenge;
        default_type "text/plain";
    }
    location / { return 404; }
}
EOF
  ln -sf /etc/nginx/sites-available/slipstream /etc/nginx/sites-enabled/slipstream
  rm -f /etc/nginx/sites-enabled/default
  nginx -t && systemctl reload nginx

  if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    ok "certificate already present"
  else
    certbot certonly --webroot -w /var/www/acme-challenge \
      -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive \
      || die "certbot failed; check that port 80 is reachable from the internet"
    ok "certificate obtained"
  fi
fi

# --- nginx configuration ---------------------------------------------------
step "Configuring nginx"

# The rate-limit zones and log format are http-level directives, so they cannot
# live in a server block. Installed as a conf.d fragment that Debian's default
# nginx.conf already includes.
cat > /etc/nginx/conf.d/slipstream-limits.conf <<'EOF'
# Slipstream shared rate-limit zones. Analysis spawns a yt-dlp process, so it
# is the expensive endpoint; authentication is limited separately to slow
# credential stuffing. The app enforces its own per-role hourly limits too —
# this layer stops a flood before it reaches Python.
limit_req_zone  $binary_remote_addr  zone=slipstream_api:10m    rate=30r/m;
limit_req_zone  $binary_remote_addr  zone=slipstream_auth:10m   rate=10r/m;
limit_req_zone  $binary_remote_addr  zone=slipstream_static:10m rate=300r/m;
limit_conn_zone $binary_remote_addr  zone=slipstream_conn:10m;

limit_req_status  429;
limit_conn_status 429;

# A pasted URL is tiny; nothing legitimate posts a large body here. Downloads
# are responses, which this does not govern.
client_max_body_size 1m;

server_tokens off;
EOF

mkdir -p /etc/nginx/snippets
install -m 644 "${INSTALL_DIR}/nginx/snippets/security-headers.conf" /etc/nginx/snippets/
install -m 644 "${INSTALL_DIR}/nginx/snippets/proxy.conf" /etc/nginx/snippets/

if [ "$USE_TLS" -eq 1 ]; then
  TEMPLATE="${INSTALL_DIR}/nginx/templates/slipstream.conf.template"
  CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
else
  TEMPLATE="${INSTALL_DIR}/nginx/templates-http/slipstream.conf.template"
  CERT_DIR=""
fi

# The templates are written for the nginx:alpine image, which expands ${VAR}
# through envsubst at container start. On bare metal sed does the same job.
sed -e "s|\${SLIPSTREAM_DOMAIN}|${DOMAIN}|g" \
    -e "s|\${SLIPSTREAM_UPSTREAM}|127.0.0.1:${PORT}|g" \
    "$TEMPLATE" > /etc/nginx/sites-available/slipstream

if [ -n "$CERT_DIR" ]; then
  # The template points at the container's cert path; certbot puts them
  # elsewhere on a host install.
  sed -i -e "s|/etc/nginx/certs/fullchain.pem|${CERT_DIR}/fullchain.pem|" \
         -e "s|/etc/nginx/certs/privkey.pem|${CERT_DIR}/privkey.pem|" \
         /etc/nginx/sites-available/slipstream
fi

ln -sf /etc/nginx/sites-available/slipstream /etc/nginx/sites-enabled/slipstream
rm -f /etc/nginx/sites-enabled/default

nginx -t || die "the generated nginx configuration is invalid; nothing was reloaded"
systemctl reload nginx
ok "nginx configured and reloaded"

# --- Certificate renewal ---------------------------------------------------
if [ "$USE_TLS" -eq 1 ]; then
  step "Setting up automatic renewal"
  # certbot's packaged timer handles renewal; it needs a reload hook so the new
  # certificate is actually picked up, which is the step people forget.
  mkdir -p /etc/letsencrypt/renewal-hooks/deploy
  cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/bin/sh
# Reload nginx after a successful renewal so it serves the new certificate.
systemctl reload nginx
EOF
  chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
  systemctl enable --now certbot.timer >/dev/null 2>&1 || true
  ok "renewal timer active with an nginx reload hook"
fi

# --- Application configuration ---------------------------------------------
step "Updating the application configuration"

ENV_FILE="${INSTALL_DIR}/.env"
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

if [ "$USE_TLS" -eq 1 ]; then
  set_env APP_URL "https://${DOMAIN}"
  set_env DOMAIN "$DOMAIN"
  set_env COOKIE_SECURE true
  # Exactly one proxy sets X-Forwarded-For. A higher value would let a client
  # prepend its own address and defeat per-IP rate limiting.
  set_env TRUSTED_PROXY_COUNT 1
  ok "configured for https://${DOMAIN}"
else
  set_env TRUSTED_PROXY_COUNT 1
  warn "no TLS: session cookies will travel in clear text"
fi

systemctl restart slipstream.service
wait_for_health "http://127.0.0.1:${PORT}/api/health/ready" 45 \
  || die "the app did not come back after the config change; journalctl -u slipstream -n 50"

# --- Firewall --------------------------------------------------------------
step "Configuring the firewall"
if have ufw; then
  # SSH first, and explicitly: enabling ufw without it locks you out of a
  # remote host.
  ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null 2>&1
  ufw allow 80/tcp >/dev/null 2>&1
  ufw allow 443/tcp >/dev/null 2>&1
  if ufw status | grep -q '^Status: active'; then
    ok "ufw already active; 22, 80, 443 allowed"
  else
    ufw --force enable >/dev/null 2>&1
    ok "ufw enabled with 22, 80, 443 allowed"
  fi
  # Port 8000 is deliberately not opened. The app listens on loopback only.
else
  warn "ufw is not installed; no firewall rules were changed"
fi

# --- Done ------------------------------------------------------------------
printf '\n'
step "Deployed"
printf '\n'
if [ "$USE_TLS" -eq 1 ]; then
  note "URL:       https://${DOMAIN}"
else
  note "URL:       http://$(hostname -I | awk '{print $1}')"
fi
note "Service:   systemctl {status,restart} slipstream"
note "Logs:      journalctl -u slipstream -f"
note "nginx:     journalctl -u nginx -f  /  /var/log/nginx/"
note "Config:    ${ENV_FILE}"
note "Backups:   sudo scripts/linux/backup.sh"
note "Updates:   sudo scripts/linux/update.sh"
printf '\n'
warn "Sign in and change the admin password now — it was printed above by the installer."
note "The seeded account cannot change settings until you do."
printf '\n'
