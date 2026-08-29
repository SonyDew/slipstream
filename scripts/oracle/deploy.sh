#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Oracle Cloud Always-Free ARM64 (Ampere A1) deployment for Slipstream.
#
#   sudo scripts/oracle/deploy.sh --domain slipstream.example.com --email you@example.com
#
# Oracle Linux differs from Ubuntu in three ways that break a naive deployment:
#
#   1. The instance ships iptables rules that REJECT everything except SSH,
#      and they persist across reboots. Opening the VCN security list is not
#      enough — both layers have to allow 80 and 443.
#   2. SELinux is enforcing. httpd_can_network_connect must be on or nginx
#      cannot reach the app, and the failure looks like a 502 with nothing
#      obvious in the nginx log.
#   3. ffmpeg is not in the base repositories; it comes from RPM Fusion, which
#      needs EPEL first.
#
# This script handles all three. See docs/ORACLE.md for the VCN steps, which
# have to be done in the Oracle web console and cannot be scripted from here.
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
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

require_root

ARCH="$(detect_arch)"
DISTRO="$(detect_distro)"

printf '\n'
step "Slipstream — Oracle Cloud deployment"
note "distro: ${DISTRO}   arch: ${ARCH}"
printf '\n'

case "$DISTRO" in
  ol|oracle|rhel|centos|almalinux|rocky) ok "detected ${DISTRO}" ;;
  ubuntu|debian)
    warn "this is a Debian-family host; scripts/ubuntu/deploy.sh fits better"
    confirm 'Continue with the Oracle script anyway?' 'yes' || die "aborted" ;;
  *) warn "unrecognised distribution '${DISTRO}'"
     confirm 'Continue?' 'yes' || die "aborted" ;;
esac

if [ "$ARCH" != "arm64" ]; then
  note "this shape is ${ARCH}, not the Ampere arm64 the free tier provides"
  note "nothing here is arm-specific, so it will still work"
fi

if [ "$USE_TLS" -eq 1 ]; then
  [ -n "$DOMAIN" ] || die "--domain is required (or pass --no-tls)"
  [ -n "$EMAIL" ]  || die "--email is required for Let's Encrypt registration"

  step "Checking DNS for ${DOMAIN}"
  RESOLVED="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
  # Oracle instances have a private primary IP; the public one comes from the
  # instance metadata service or an external lookup.
  PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo '')"

  [ -n "$RESOLVED" ] || die "${DOMAIN} does not resolve. Point an A record at this instance first."
  if [ -n "$PUBLIC_IP" ] && [ "$RESOLVED" != "$PUBLIC_IP" ]; then
    warn "${DOMAIN} resolves to ${RESOLVED}; this instance appears to be ${PUBLIC_IP}"
    confirm 'Continue?' 'yes' || die "aborted"
  else
    ok "${DOMAIN} -> ${RESOLVED}"
  fi
else
  DOMAIN="${DOMAIN:-_}"
fi

# --- Application -----------------------------------------------------------
step "Installing the application"
BIND_HOST=127.0.0.1 PORT="$PORT" INSTALL_DIR="$INSTALL_DIR" \
  "${SCRIPT_DIR}/../linux/install.sh"

# --- nginx -----------------------------------------------------------------
step "Installing nginx"
PKG="$(detect_pkg_manager)"
"$PKG" install -y -q nginx
ok "nginx installed"

# --- Firewall: the Oracle-specific part ------------------------------------
step "Opening the host firewall"

# Oracle Linux images ship an iptables ruleset that REJECTs everything except
# SSH, and it is saved to /etc/iptables/rules.v4 so it survives reboots. Both
# firewalld (if present) and the raw rules have to be dealt with.
if have firewall-cmd && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http >/dev/null
  firewall-cmd --permanent --add-service=https >/dev/null
  firewall-cmd --reload >/dev/null
  ok "firewalld: http and https allowed"
elif have iptables; then
  # Insert before the blanket REJECT rather than appending, which would place
  # the ACCEPT after it where it never matches.
  for p in 80 443; do
    if ! iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null; then
      iptables -I INPUT 5 -p tcp --dport "$p" -m state --state NEW -j ACCEPT
      ok "iptables: opened ${p}/tcp"
    else
      ok "iptables: ${p}/tcp already open"
    fi
  done

  if have netfilter-persistent; then
    netfilter-persistent save >/dev/null 2>&1
    ok "rules saved"
  elif [ -d /etc/iptables ]; then
    iptables-save > /etc/iptables/rules.v4
    ok "rules saved to /etc/iptables/rules.v4"
  else
    warn "could not persist the iptables rules; they will be lost on reboot"
    note "save them with: iptables-save > /etc/iptables/rules.v4"
  fi
else
  warn "no recognised firewall tool; nothing was changed"
fi

printf '\n'
warn "The host firewall is only half of it."
note "Oracle's VCN security list must ALSO allow ingress on 80 and 443:"
note "  Console -> Networking -> VCN -> Subnet -> Security List -> Add Ingress Rules"
note "  Source 0.0.0.0/0, protocol TCP, destination ports 80 and 443"
note "Without that, the certificate request below will fail. See docs/ORACLE.md."
printf '\n'

# --- SELinux ---------------------------------------------------------------
step "Configuring SELinux"

if have getenforce && [ "$(getenforce)" != "Disabled" ]; then
  # Without this, nginx cannot open a socket to the app and every request
  # returns 502 with an audit denial that never appears in the nginx log.
  if have setsebool; then
    setsebool -P httpd_can_network_connect 1
    ok "httpd_can_network_connect enabled"
  else
    die "SELinux is $(getenforce) but setsebool is missing; install policycoreutils"
  fi

  if have semanage; then
    # nginx serves nothing from disk here (everything is proxied), but the
    # ACME webroot is read directly.
    semanage fcontext -a -t httpd_sys_content_t '/var/www/acme-challenge(/.*)?' 2>/dev/null || true
    ok "labelled the ACME webroot"
  fi
else
  ok "SELinux is disabled; nothing to configure"
fi

# --- Certificate ------------------------------------------------------------
if [ "$USE_TLS" -eq 1 ]; then
  step "Obtaining a certificate"

  "$PKG" install -y -q certbot python3-certbot-nginx 2>/dev/null || {
    warn "certbot is not in the enabled repositories; trying EPEL"
    "$PKG" install -y -q oracle-epel-release-el9 2>/dev/null \
      || "$PKG" install -y -q epel-release 2>/dev/null \
      || die "could not enable EPEL; install certbot manually"
    "$PKG" install -y -q certbot python3-certbot-nginx
  }

  mkdir -p /var/www/acme-challenge
  chown -R nginx:nginx /var/www/acme-challenge
  have restorecon && restorecon -R /var/www/acme-challenge 2>/dev/null || true

  # Temporary HTTP-only block so the http-01 challenge is answerable before any
  # certificate exists.
  cat > /etc/nginx/conf.d/slipstream-acme.conf <<EOF
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
  # Oracle Linux's default nginx.conf has its own server block on 80, which
  # would shadow ours.
  if [ -f /etc/nginx/nginx.conf ] && grep -q 'server_name  _;' /etc/nginx/nginx.conf; then
    note "the packaged default server block is still present; ours takes precedence by name"
  fi

  nginx -t && systemctl enable --now nginx >/dev/null 2>&1
  systemctl reload nginx

  if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    ok "certificate already present"
  else
    certbot certonly --webroot -w /var/www/acme-challenge \
      -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive \
      || die "certbot failed. The usual cause is the VCN security list still blocking port 80."
    ok "certificate obtained"
  fi

  rm -f /etc/nginx/conf.d/slipstream-acme.conf
fi

# --- nginx configuration ---------------------------------------------------
step "Configuring nginx"

# http-level directives cannot live in a server block. Oracle Linux's nginx.conf
# includes /etc/nginx/conf.d/*.conf, so this fragment is picked up.
cat > /etc/nginx/conf.d/00-slipstream-limits.conf <<'EOF'
# Slipstream shared rate-limit zones. Loaded before the server block: the
# filename sorts first because a zone must be defined before it is referenced.
limit_req_zone  $binary_remote_addr  zone=slipstream_api:10m    rate=30r/m;
limit_req_zone  $binary_remote_addr  zone=slipstream_auth:10m   rate=10r/m;
limit_req_zone  $binary_remote_addr  zone=slipstream_static:10m rate=300r/m;
limit_conn_zone $binary_remote_addr  zone=slipstream_conn:10m;

limit_req_status  429;
limit_conn_status 429;

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

# The templates target the nginx:alpine image, which expands ${VAR} via envsubst
# at container start. sed does the same job on a host install.
sed -e "s|\${SLIPSTREAM_DOMAIN}|${DOMAIN}|g" \
    -e "s|\${SLIPSTREAM_UPSTREAM}|127.0.0.1:${PORT}|g" \
    "$TEMPLATE" > /etc/nginx/conf.d/10-slipstream.conf

if [ -n "$CERT_DIR" ]; then
  sed -i -e "s|/etc/nginx/certs/fullchain.pem|${CERT_DIR}/fullchain.pem|" \
         -e "s|/etc/nginx/certs/privkey.pem|${CERT_DIR}/privkey.pem|" \
         /etc/nginx/conf.d/10-slipstream.conf
fi

nginx -t || die "the generated nginx configuration is invalid; nothing was reloaded"
systemctl reload nginx
ok "nginx configured and reloaded"

# --- Certificate renewal ---------------------------------------------------
if [ "$USE_TLS" -eq 1 ]; then
  step "Setting up automatic renewal"
  mkdir -p /etc/letsencrypt/renewal-hooks/deploy
  cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/bin/sh
# Reload nginx after a renewal so it serves the new certificate.
systemctl reload nginx
EOF
  chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

  # Oracle Linux's certbot package has no timer, unlike Debian's.
  if systemctl list-unit-files | grep -q '^certbot.timer'; then
    systemctl enable --now certbot.timer >/dev/null 2>&1
    ok "certbot.timer enabled"
  else
    cat > /etc/systemd/system/certbot-renew.timer <<'EOF'
[Unit]
Description=Renew Let's Encrypt certificates twice daily

[Timer]
OnCalendar=*-*-* 03,15:00:00
# Spread the load on Let's Encrypt's servers; without it every host installed
# from this script would hit them at the same minute.
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
EOF
    cat > /etc/systemd/system/certbot-renew.service <<'EOF'
[Unit]
Description=Renew Let's Encrypt certificates

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --webroot -w /var/www/acme-challenge
EOF
    systemctl daemon-reload
    systemctl enable --now certbot-renew.timer >/dev/null 2>&1
    ok "certbot-renew.timer created and enabled"
  fi
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
fi
# One proxy (nginx). Higher would let a client spoof its own X-Forwarded-For
# and bypass per-IP rate limiting.
set_env TRUSTED_PROXY_COUNT 1

# The free tier's boot volume is 50 GB and the outbound link is modest; two
# concurrent jobs with a short file TTL keeps the disk from filling, which
# would take the database down with it.
set_env MAX_CONCURRENT_DOWNLOADS 2
set_env TEMP_FILE_TTL 3600
ok "configured for the free-tier shape"

systemctl restart slipstream.service
wait_for_health "http://127.0.0.1:${PORT}/api/health/ready" 60 \
  || die "the app did not come back; journalctl -u slipstream -n 50"

# --- Done ------------------------------------------------------------------
printf '\n'
step "Deployed"
printf '\n'
if [ "$USE_TLS" -eq 1 ]; then
  note "URL:       https://${DOMAIN}"
else
  note "URL:       http://${PUBLIC_IP:-<instance ip>}"
fi
note "Service:   systemctl {status,restart} slipstream"
note "Logs:      journalctl -u slipstream -f"
note "Config:    ${ENV_FILE}"
note "Backups:   sudo scripts/linux/backup.sh"
note "Updates:   sudo scripts/linux/update.sh"
printf '\n'
warn "Sign in and change the admin password now — the installer printed it above."
printf '\n'
note "If the site is unreachable, check the VCN security list before anything else."
note "It is the single most common cause on Oracle Cloud. See docs/ORACLE.md."
printf '\n'
