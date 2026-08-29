# Ubuntu VPS deployment

A public, TLS-terminated Slipstream on an x86_64 Ubuntu server with your own domain.

For ARM on Oracle's free tier, use [ORACLE.md](ORACLE.md) — the divergences are real, not
cosmetic.

---

## What you need

- Ubuntu 22.04 or 24.04, x86_64. 1 vCPU / 1 GB works; 2 / 2 is comfortable.
- Root or sudo.
- A domain with an **A record already pointing at the server's IP.** Not "about to". The
  certificate request fails without it.
- Ports 80 and 443 reachable from the internet.
- An email address for Let's Encrypt expiry notices.

Check DNS before you start:

```bash
dig +short your-domain.com
curl -s https://api.ipify.org
```

Those two must match. The deploy script checks this itself and refuses to proceed
otherwise, because a failed certificate request consumes a Let's Encrypt rate-limit attempt
and the limits are per-domain per-week.

---

## The one-command path

```bash
git clone <url> slipstream && cd slipstream
sudo scripts/ubuntu/deploy.sh --domain your-domain.com --email you@example.com
```

Ten to fifteen minutes. In order, it:

1. Verifies the distro and that DNS resolves to this host.
2. Runs `scripts/linux/install.sh` with `BIND_HOST=127.0.0.1` — the app is never directly
   reachable.
3. Installs nginx and certbot.
4. Writes a temporary HTTP-only server block so the http-01 challenge can be served.
5. Obtains the certificate via `certbot certonly --webroot`.
6. Installs `conf.d/slipstream-limits.conf` for the http-level rate-limit zones.
7. Expands `nginx/templates/slipstream.conf.template` with `sed` — the envsubst equivalent
   for bare metal — and rewrites the container certificate paths to certbot's real ones.
8. Runs `nginx -t` **before** reloading. An invalid config reloads nothing.
9. Installs a renewal deploy hook that reloads nginx.
10. Sets `APP_URL`, `DOMAIN`, `COOKIE_SECURE=true` and `TRUSTED_PROXY_COUNT=1` in `.env`.
11. Configures ufw.
12. Waits for health and runs `app.cli verify`.
13. Prints the generated admin credentials.

**Write down the credentials.** They are printed once.

For an internal deployment with no public hostname:

```bash
sudo scripts/ubuntu/deploy.sh --no-tls
```

That gives you nginx on port 80 with no certificate. Only for a private network — session
cookies travel in plain text.

---

## What it configures, and why

### The app binds loopback only

`127.0.0.1:8000`. nginx is the only thing that talks to it. Port 8000 stays closed in ufw
deliberately: an open 8000 lets anyone bypass nginx entirely and reach the app over plain
HTTP, which discards TLS, the rate-limit zones and the security headers in one step.

### `TRUSTED_PROXY_COUNT=1`

Exactly one proxy — the nginx you just installed. The app takes the client IP from
`X-Forwarded-For` one hop in.

Getting this wrong breaks rate limiting in one of two ways. At `0`, every request appears to
come from `127.0.0.1` and one user exhausts everyone's quota. Above `1`, a client can inject
its own `X-Forwarded-For` and reset its counter whenever it likes.

### `COOKIE_SECURE=true`

Set explicitly rather than inferred. The app sees plain HTTP from nginx and cannot tell that
the outside edge was encrypted.

### ufw

```
22/tcp    ALLOW    OpenSSH
80/tcp    ALLOW
443/tcp   ALLOW
```

SSH is allowed **first and explicitly**, before the firewall is enabled. Enabling ufw
without it locks you out of a remote host, and the recovery is a console session from your
provider's dashboard.

### nginx

`/etc/nginx/sites-available/slipstream`, symlinked into `sites-enabled`, with the default
site removed. Rate-limit zones go in `/etc/nginx/conf.d/slipstream-limits.conf` because
`limit_req_zone` is an http-level directive and cannot live inside a server block.

Locations, and the reason for each:

| Location | Treatment | Why |
| --- | --- | --- |
| `~ ^/api/auth/(login\|register\|change-password)$` | 10 r/m | Credential endpoints |
| `~ ^/api/jobs/[^/]+/file$` | buffering off, 3600s timeout, ranges | Large streaming responses |
| `^~ /api/health` | unlimited, no access log | Monitoring should not consume quota |
| `^~ /api/` | 30 r/m, burst 20 | |
| `^~ /assets/` | `expires 1y`, immutable | Content-hashed filenames |
| `/` | `no-cache, must-revalidate` | A stale shell references dead asset hashes |

The file endpoint is the one that matters. With buffering on — nginx's default — a 2 GiB
response is buffered to disk before a single byte reaches the client, which either stalls the
download for minutes or fills `/var/cache/nginx`.

Both `/assets/` and `/` re-include the security-header snippet. In nginx, any `add_header` in
a location **replaces** the entire inherited set rather than adding to it, so setting
`Cache-Control` there would silently drop the CSP and HSTS from every asset response.

HSTS is `max-age=31536000; includeSubDomains` **without `preload`**. Preloading is a
years-long commitment baked into browser binaries and it applies to every subdomain of your
apex. That is not a decision a deployment script should make for you.

---

## After deploying

```bash
# 1. The API answers
curl https://your-domain.com/api/health

# 2. The SPA is served, not JSON
curl -sI https://your-domain.com/ | head -3

# 3. The admin API rejects anonymous callers — must be 401 or 403
curl -o /dev/null -w '%{http_code}\n' https://your-domain.com/api/admin/stats

# 4. HTTP redirects to HTTPS
curl -sI http://your-domain.com/ | head -3

# 5. Security headers are present
curl -sI https://your-domain.com/ | grep -iE 'strict-transport|content-security|x-frame'

# 6. And on assets too — this is what the re-include is for
curl -sI https://your-domain.com/assets/ | grep -i content-security
```

Then sign in, **change the admin password**, and complete one real download end to end.
Admin mutations stay locked until the password is changed.

Set up backups: [BACKUPS.md](BACKUPS.md). Then read the hardening checklist at the end of
[SECURITY.md](../SECURITY.md).

---

## Operations

```bash
sudo systemctl status slipstream
sudo journalctl -u slipstream -f
sudo systemctl restart slipstream

cd /opt/slipstream/backend
sudo -u slipstream .venv/bin/python -m app.cli verify
sudo -u slipstream .venv/bin/python -m app.cli stats
sudo -u slipstream .venv/bin/python -m app.cli reset-password --username admin
```

Run CLI commands as the `slipstream` user. As root they create files the service user cannot
then write to, which produces confusing permission errors later.

### Updating

```bash
sudo scripts/linux/update.sh
sudo scripts/linux/update.sh --ytdlp-only    # a site broke today
```

yt-dlp is the dependency with a real cadence — platforms change their players constantly.
Monthly, or whenever extraction breaks. See [UPDATES.md](UPDATES.md).

### Backups

```bash
sudo scripts/linux/backup.sh
sudo scripts/linux/backup.sh /mnt/backups
KEEP=30 sudo scripts/linux/backup.sh
```

Uses SQLite's online backup API, so it is safe against a live instance with no downtime. A
plain file copy of a WAL-mode database can restore to a corrupt state.

Enable the timer if you want it unattended:

```bash
sudo systemctl enable --now slipstream-backup.timer
sudo systemctl list-timers | grep slipstream
```

Disabled by default because a scheduled job that writes to disk should be a deliberate
choice.

### Certificate renewal

certbot's packaged timer handles it. The deploy script adds a deploy hook that reloads
nginx, which matters: **a renewed certificate that nginx has not reloaded is still the old
certificate.** Renewal succeeds, the site keeps serving the expiring cert, and nothing looks
wrong until it expires.

```bash
sudo certbot renew --dry-run
sudo systemctl list-timers | grep certbot
sudo certbot certificates
```

---

## Docker instead

If you prefer containers:

```bash
cp .env.example .env
# set SECRET_KEY, DOMAIN, APP_URL, COOKIE_SECURE=true
docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d
```

The overlay sets `ports: !override []` on `app` — the base file publishes on
`127.0.0.1:8000` and behind nginx that mapping is unnecessary, so it is removed rather than
narrowed. `!override` needs Compose 2.24 or newer; check with `docker compose version`.

It also sets `COOKIE_SECURE=true`, `TRUSTED_PROXY_COUNT=1`, and adds an nginx service
mounting `nginx/templates`, `nginx/snippets`, `nginx/nginx.conf`, the certificate directory
(`CERT_DIR`, default `./deploy/ubuntu/certs`) and the ACME webroot.

Get certificates onto the host first — `deploy/ubuntu/certs/README.md` covers it. One
gotcha: `/etc/letsencrypt/live/<domain>/` contains **symlinks** into `../../archive/`. A
Docker mount of just the `live` directory gives the container dangling links. Mount
`/etc/letsencrypt` whole, or copy the real files.

---

## Troubleshooting

**502 Bad Gateway** — nginx cannot reach the app.

```bash
sudo systemctl status slipstream
curl -sI http://127.0.0.1:8000/api/health
sudo tail -50 /var/log/nginx/error.log
```

**certbot fails the challenge** — port 80 is not reachable, or DNS is wrong.

```bash
dig +short your-domain.com     # must equal the server's public IP
sudo ufw status
curl -I http://your-domain.com/.well-known/acme-challenge/test
```

Also check your provider's firewall or security group, which is separate from ufw.

**Everyone hits the rate limit at once** — `TRUSTED_PROXY_COUNT` is `0`, so all requests
look like they come from `127.0.0.1`.

```bash
grep TRUSTED_PROXY_COUNT /opt/slipstream/.env    # must be 1
```

**Signed out on every page load** — `COOKIE_SECURE=true` without working TLS, so the browser
declines to send the cookie back. Either fix TLS or unset it (and do not expose the instance
publicly).

**Downloads stall near completion** — `proxy_buffering` is on for the file endpoint. Confirm
the `~ ^/api/jobs/[^/]+/file$` location survived any edits you made.

**`nginx -t` fails after you edited a template** — most likely an unexpanded `${VAR}`. On
bare metal the deploy script expands placeholders with `sed`; anything you add by hand must
be a literal value.

**Missing security headers on `/assets/`** — an `add_header` in that location without
re-including the snippet. See above; this one is easy to reintroduce.

More in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Manual install

If you want to do it yourself rather than run the script:

```bash
# 1. The app, bound to loopback
sudo BIND_HOST=127.0.0.1 scripts/linux/install.sh

# 2. nginx and certbot
sudo apt-get update && sudo apt-get install -y nginx certbot python3-certbot-nginx

# 3. Certificate — needs a temporary HTTP server block serving the webroot
sudo mkdir -p /var/www/acme-challenge
sudo certbot certonly --webroot -w /var/www/acme-challenge \
  -d your-domain.com --email you@example.com --agree-tos --non-interactive

# 4. Rate-limit zones at the http level
sudo cp nginx/snippets/*.conf /etc/nginx/snippets/
# limit_req_zone directives go in /etc/nginx/conf.d/slipstream-limits.conf

# 5. Expand the template
sed -e 's|${SLIPSTREAM_DOMAIN}|your-domain.com|g' \
    -e 's|${SLIPSTREAM_UPSTREAM}|127.0.0.1:8000|g' \
    nginx/templates/slipstream.conf.template \
  | sudo tee /etc/nginx/sites-available/slipstream > /dev/null

# 6. Point the cert paths at certbot's real location, not the container path
sudo sed -i 's|/etc/nginx/certs|/etc/letsencrypt/live/your-domain.com|g' \
  /etc/nginx/sites-available/slipstream

# 7. Enable, test, reload — in that order
sudo ln -sf /etc/nginx/sites-available/slipstream /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 8. Tell the app it is behind TLS and one proxy
sudo tee -a /opt/slipstream/.env <<'EOF'
APP_URL=https://your-domain.com
DOMAIN=your-domain.com
COOKIE_SECURE=true
TRUSTED_PROXY_COUNT=1
EOF
sudo systemctl restart slipstream

# 9. Firewall — SSH first
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable

# 10. A renewal hook, so nginx picks up new certificates
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

Steps 6, 7 and 10 are the ones people skip and then debug for an hour.
