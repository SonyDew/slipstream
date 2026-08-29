# Troubleshooting

Symptoms, in rough order of how often they come up. Each entry says how to confirm the cause
before changing anything.

---

## Start here

```bash
# Docker
docker compose ps
docker compose logs --tail=100 app
docker compose exec app python -m app.cli verify

# Bare metal
sudo systemctl status slipstream
sudo journalctl -u slipstream -n 100 --no-pager
cd /opt/slipstream/backend && sudo -u slipstream .venv/bin/python -m app.cli verify

# Windows
cd backend; .venv\Scripts\python.exe -m app.cli verify
```

`verify` checks the schema, the admin account and the toolchain, and is the fastest way to
narrow "something is wrong" to a specific subsystem.

Then the three endpoints that tell you which layer is broken:

```bash
curl -s http://127.0.0.1:8000/api/health          # the app itself
curl -s https://your-domain/api/health            # the app through the proxy
curl -sI https://your-domain/                     # the SPA is being served
```

If the first works and the second does not, the problem is nginx or the firewall, not the app.

---

## The app will not start

### `SECRET_KEY is required when ENVIRONMENT=production`

Working as intended. Generate and set one:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

The entrypoint refuses rather than generating a per-boot key, which would log everyone out on
every restart and present as a mysterious bug instead of a configuration error.

### `/app/data is not writable by uid 10001`

A bind-mounted host directory owned by your user. The container runs unprivileged.

```bash
sudo chown -R 10001:10001 ./data
```

Or use the named volume the base compose file provides, which avoids the problem entirely.

### Port already in use

```bash
sudo ss -tlnp | grep :8000        # Linux
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess   # Windows
```

`start.ps1` names the owning process for you.

### Crash loop, no obvious error

```bash
sudo journalctl -u slipstream -n 200 --no-pager
```

The unit sets `StartLimitBurst=5` / `StartLimitIntervalSec=300`, so after five failures in five
minutes systemd stops trying. Clear it with `systemctl reset-failed slipstream` once you have
fixed the cause.

### Import errors after a Python upgrade

The venv references the old interpreter. Rebuild it:

```bash
cd /opt/slipstream/backend
sudo -u slipstream rm -rf .venv
sudo -u slipstream python3 -m venv .venv
sudo -u slipstream .venv/bin/pip install -r requirements.txt
```

---

## Nothing at `/`, but `/api/health` works

`frontend/dist/index.html` does not exist, so there is no SPA to serve. The app logs a warning
about this at startup.

```bash
npm --prefix frontend run build
ls frontend/dist/index.html
```

For Docker, the image builds the SPA in its first stage — if it is missing, the build failed
and the image is stale. Rebuild with `docker compose build --no-cache app`.

`FRONTEND_DIST` overrides the location if you build elsewhere.

---

## Blank page, or `Unexpected token '<'`

The browser is holding a cached `index.html` referencing asset hashes that no longer exist
after a deploy. Hard-refresh: Ctrl+Shift+R.

The nginx config sets `Cache-Control: no-cache, must-revalidate` on `/` specifically to prevent
this. If it recurs, that header was lost — most likely because an `add_header` was added to
that location without re-including the security-header snippet, since in nginx `add_header`
inside a location **replaces** the whole inherited set.

```bash
curl -sI https://your-domain/ | grep -i cache-control
```

`Unexpected token '<'` specifically means an asset request returned HTML. The app returns a real
404 for a missing asset rather than the SPA shell, so if you are seeing this, suspect a proxy in
front rewriting paths.

---

## 502 Bad Gateway

nginx cannot reach the app.

```bash
sudo systemctl status slipstream
curl -sI http://127.0.0.1:8000/api/health
sudo tail -50 /var/log/nginx/error.log
```

**On Oracle Linux, SELinux first.** This is the most common 502 on that platform, and the reason
appears in the audit log, never in the nginx log:

```bash
sudo getsebool httpd_can_network_connect        # must be "on"
sudo setsebool -P httpd_can_network_connect 1
sudo ausearch -m avc -ts recent
```

If the app answers on loopback and nginx still cannot reach it, check the `upstream` address in
the server block matches where the app is actually bound.

---

## Connection times out with nothing in any log

The packet never arrived, so there is nothing to log. A firewall dropped it.

**Oracle Cloud** has two layers and both must allow the port:

1. **VCN security list** — in the web console: Networking → VCN → Subnets → Security Lists →
   ingress rules for 80 and 443. Cannot be configured from inside the instance.
2. **iptables** on the instance:

```bash
sudo iptables -L INPUT -n --line-numbers
```

Your ACCEPT rules must appear **above** the blanket REJECT. Appending puts them after it, where
they never match, and `iptables -L` looks correct while the port stays closed:

```bash
sudo iptables -I INPUT 5 -p tcp --dport 443 -m state --state NEW -j ACCEPT
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

**Ubuntu**: `sudo ufw status`. Also check your provider's security group, which is separate.

---

## Authentication

### Signed out on every page load

The session cookie is not making the round trip.

- **`COOKIE_SECURE=true` without working TLS.** The browser will not send a `Secure` cookie over
  plain HTTP. Either fix TLS or unset it — and if you unset it, do not expose the instance
  publicly.
- **Mismatched origin.** In development, use the Vite proxy on `:5173` rather than hitting
  `:8000` directly from a page served on `:5173`.
- **`SECRET_KEY` changed.** Every existing session becomes unverifiable. Check `.env` still has
  the original value; if it was regenerated, users simply have to sign in again.

```bash
curl -sI https://your-domain/api/auth/me | grep -i set-cookie
```

### `csrf_failed` on every mutation

The `slipstream_csrf` cookie is not present, or the client is not echoing it as
`X-CSRF-Token`. Both cookies must reach the browser and the header must match.

If you are calling the API directly, read the cookie and send it back:

```bash
CSRF=$(awk '/slipstream_csrf/ {print $7}' cookies.txt)
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" ...
```

### `password_change_required` as an admin

The account is still flagged as using its seeded temporary password. It can read the admin panel
but not mutate anything. Change the password under Account. This is deliberate, not a bug.

### Locked out entirely

```bash
# Docker
docker compose exec app python -m app.cli reset-password --username admin

# Bare metal
cd /opt/slipstream/backend
sudo -u slipstream .venv/bin/python -m app.cli reset-password --username admin

# Windows
cd backend; .venv\Scripts\python.exe -m app.cli reset-password --username admin
```

Omit `--password` to be prompted, keeping it out your shell history and out of `ps`.

If there is no admin at all:

```bash
python -m app.cli create-admin --username you --email you@example.com
```

---

## Rate limiting

### Everyone is rate-limited at once

`TRUSTED_PROXY_COUNT` is `0` behind a proxy, so every request appears to come from the proxy's
address and all users share one bucket.

```bash
grep TRUSTED_PROXY_COUNT /opt/slipstream/.env      # must equal your proxy depth
```

One nginx in front means `1`. Restart after changing it.

### Rate limits have no effect

The opposite error: `TRUSTED_PROXY_COUNT` is higher than the real proxy count, so a client can
inject its own `X-Forwarded-For` and reset its counter at will. Set it to the exact number of
proxies **you control**.

### 429 from nginx rather than the app

nginx has its own zones, independent of the app's. Raise the rates in
`nginx/nginx.conf` (or `conf.d/slipstream-limits.conf` on bare metal) if the defaults are too
tight for your usage:

| Zone | Default |
| --- | --- |
| `slipstream_api` | 30 r/m |
| `slipstream_auth` | 10 r/m |
| `slipstream_static` | 300 r/m |

---

## Downloads

### Jobs stay `queued` forever

The queue is in-process. Either the worker never started, or **you are running more than one
uvicorn worker**, in which case the job is sitting in another process's memory.

```bash
ps aux | grep uvicorn        # exactly one process
```

If there are several, that is the cause. The entrypoint forces `WEB_CONCURRENCY=1` and the
systemd unit hardcodes `--workers 1`; if you overrode either, undo it. Scale with
`MAX_CONCURRENT_DOWNLOADS` instead.

Check the startup logs for the worker task and the cleanup loop starting.

### `ffmpeg_missing`, or no MP3 options

ffmpeg is not on the `PATH` of the *server process*, which is not always your shell's. Under
systemd the environment is minimal by design.

```bash
which ffmpeg ffprobe
sudo -u slipstream which ffmpeg          # what the service user sees
```

Set absolute paths:

```ini
FFMPEG_PATH=/usr/bin/ffmpeg
FFPROBE_PATH=/usr/bin/ffprobe
```

On Oracle Linux, ffmpeg comes from RPM Fusion, which needs EPEL first — see
[ORACLE.md](ORACLE.md).

The app degrades honestly without it: MP3 options disappear, adaptive-only video rungs are
hidden, and the analyze response explains why in `warnings`. That is not a silent failure, it is
the design.

### A site that worked yesterday now fails

**Update yt-dlp.** This fixes the overwhelming majority of these.

```bash
sudo scripts/linux/update.sh --ytdlp-only
# or
docker compose exec app pip install --upgrade yt-dlp && docker compose restart app
```

If it still fails, check whether yt-dlp itself can see the formats:

```bash
yt-dlp -F '<the url>'
```

If yt-dlp cannot either, the fix belongs upstream at
https://github.com/yt-dlp/yt-dlp/issues. If yt-dlp works and Slipstream does not, that is worth
reporting here with both outputs.

### `blocked_target`

The SSRF guard rejected the resolved address — private, loopback, link-local or multicast.
Expected for anything on your LAN.

`ALLOW_PRIVATE_NETWORK_TARGETS=true` lifts it. **Test only.** In production it turns any
submitted URL into a request originating inside your network, with cloud metadata endpoints as
the obvious target.

### `private_content`, `auth_required_content`, `drm_protected`, `geo_restricted`

Not bugs. The media is not publicly accessible, and Slipstream does not circumvent access
controls. There is no flag, cookie file or credential option that changes this — it is what the
project is, not a limitation waiting to be lifted.

`geo_restricted` means the *server's* location is blocked, not yours.

### The requested quality is not offered

The source does not have it. `video_options` contains only rungs the extractor actually
reported. A 4K option that silently delivered 1080p would be worse, because you could not tell.

Without ffmpeg, adaptive-only rungs are also hidden — they need muxing. Install it.

### Downloads stall near completion

`proxy_buffering` is on for the file endpoint, so nginx is buffering the whole response to disk
before sending any of it. Confirm the location survived your edits:

```nginx
location ~ ^/api/jobs/[^/]+/file$ {
    proxy_buffering         off;
    proxy_request_buffering off;
    proxy_read_timeout      3600s;
    proxy_force_ranges      on;
}
```

### Downloads are slow

Muxing is CPU-bound. Watch ffmpeg during a download:

```bash
top -b -n 1 | grep ffmpeg
```

If it is pinned, that is your ceiling. Lower `MAX_CONCURRENT_DOWNLOADS` so jobs compete less —
counterintuitive, but two jobs each getting half a core finish later than two jobs run in
sequence.

### `download_expired` on a job that just finished

`TEMP_FILE_TTL` elapsed, or the cleanup sweep removed the file. Default is 2 hours; the Oracle
profile lowers it to 1 because of the 50 GB boot volume. Raise it if your users need longer:

```ini
TEMP_FILE_TTL=14400
```

### `file_too_large` / `video_too_long`

`MAX_FILE_SIZE` (bytes) and `MAX_VIDEO_DURATION` (seconds). Both runtime-editable in the admin
panel. Raise deliberately — the ceiling on temp usage is roughly concurrency × max file size,
and a full disk takes the database down with it.

---

## Disk

### `data/temp/` growing without bound

The cleanup loop is not running, or the TTL is too long.

```bash
du -sh /opt/slipstream/data/temp
curl -s http://127.0.0.1:8000/api/health/storage
```

Force a sweep:

```bash
python -m app.cli cleanup
```

If temp keeps growing after a manual sweep works, the background loop is not running — check
the startup logs. Multiple workers also cause this, since two loops race over the same tree.

### Disk full

```bash
df -h /
du -sh /opt/slipstream/data/*
```

Clear temp first (`app.cli cleanup`), then prune history (`HISTORY_RETENTION_DAYS`), then look
at logs and old backups. On the Oracle free tier the 50 GB boot volume fills faster than people
expect.

---

## Certificates

### Expired, but renewal "succeeded"

nginx was never reloaded. **A renewed certificate that nginx has not reloaded is still the old
certificate** — renewal succeeds, the site keeps serving the expiring cert, and nothing looks
wrong until it fails.

```bash
sudo ls /etc/letsencrypt/renewal-hooks/deploy/
sudo certbot certificates
sudo systemctl reload nginx
```

The deploy scripts install a hook for this. Confirm it is there and executable.

### No renewal timer at all

Oracle Linux's certbot package ships none, unlike Debian's. The deploy script creates
`certbot-renew.timer` when it finds none.

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

Without a timer the certificate silently expires in 90 days.

### certbot fails the http-01 challenge

Port 80 must be reachable from the internet, and DNS must point here.

```bash
dig +short your-domain.com
curl -s https://api.ipify.org                                  # must match
curl -I http://your-domain.com/.well-known/acme-challenge/test # from another machine
```

On Oracle, the VCN security list is the usual culprit. Note that failed attempts count against
Let's Encrypt's per-domain weekly rate limit, so fix the cause rather than retrying.

### Docker container sees dangling certificate links

`/etc/letsencrypt/live/<domain>/` contains **symlinks** into `../../archive/`. Mounting only the
`live` directory gives the container broken links. Mount `/etc/letsencrypt` whole, or copy the
real files. See `deploy/*/certs/README.md`.

---

## nginx

### `nginx -t` fails after editing a template

Most likely an unexpanded `${VAR}`. **Only files under `/etc/nginx/templates` pass through
envsubst** in the `nginx:alpine` image; a placeholder anywhere else reaches nginx literally and
fails to parse.

On bare metal the deploy scripts expand placeholders with `sed`, so anything you add by hand
must be a literal value.

```bash
sudo nginx -t
grep -rn '\${' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/
```

### Security headers missing on some responses

An `add_header` in that location without re-including the snippet. In nginx, `add_header` inside
a location **replaces** the entire inherited set rather than adding to it.

```bash
curl -sI https://your-domain/ | grep -i content-security
curl -sI https://your-domain/assets/ | grep -i content-security     # both must have it
```

Fix by adding `include /etc/nginx/snippets/security-headers.conf;` inside the location.

### `limit_req_zone` directive not allowed here

It is an http-level directive and cannot go inside a `server` block. On bare metal it belongs in
`conf.d/slipstream-limits.conf` (Ubuntu) or `00-slipstream-limits.conf` (Oracle) — numbered so
the zones are defined before the server block references them.

---

## Database

### `database is locked`

SQLite under write contention. Rare in WAL mode with a single worker; if you see it regularly,
something is holding a long write transaction, or there is more than one process writing.

```bash
ps aux | grep uvicorn      # must be exactly one
```

### Recent data missing after a restore

The backup was taken with `cp` rather than the online backup API, so it caught the `.db` without
the `-wal`. Every committed-but-not-checkpointed transaction is gone.

Use `docker/backup.sh` or `scripts/linux/backup.sh`. See [BACKUPS.md](BACKUPS.md) — this failure
is exactly why they exist.

### `alembic upgrade head` fails

Restore the backup and report it with the error. **Do not edit the `alembic_version` table** to
make the error go away — that leaves the schema and the recorded revision disagreeing, which
turns every future migration into a new failure.

```bash
sudo -u slipstream .venv/bin/python -m alembic current
sudo -u slipstream .venv/bin/python -m alembic history
```

### Integrity check

```bash
sqlite3 data/db/slipstream.db 'PRAGMA integrity_check;'
```

Anything other than `ok` means restore from backup.

---

## Development

### Vite proxy returns 404 for `/api`

The backend is not running, or `VITE_API_TARGET` points elsewhere. Default is
`http://127.0.0.1:8000`. Inside a container, `localhost` is the container — the dev compose
overlay sets `http://app:8000` for exactly that reason.

### Tests fail with SSRF or network errors

The suite sets `ALLOW_PRIVATE_NETWORK_TARGETS` so it can reach a local fixture server. If you
overrode it in a `.env` that the tests pick up, remove it.

### `recharts is bundled into the entry chunk`

Something imports it statically outside the lazy boundary. recharts plus d3 is the largest
dependency in the tree; in the entry chunk, every visitor downloads it to view the home page.

```bash
grep -rn 'recharts' frontend/src --include='*.tsx' --include='*.ts'
```

Only `components/admin/charts.tsx` should reference it, and it must be reached through a
`lazy()` boundary.

### `npm run lint` fails on warnings

`--max-warnings 0` is deliberate. A warning nobody has to fix accumulates until the output is
noise and real problems hide in it. Fix it, or justify a targeted disable comment.

---

## Getting logs

```bash
# Docker
docker compose logs -f app
docker compose logs --tail=200 app > slipstream.log
docker compose exec app cat /app/data/logs/slipstream.log

# Bare metal
sudo journalctl -u slipstream -f
sudo journalctl -u slipstream --since '1 hour ago' --no-pager > slipstream.log
sudo tail -f /opt/slipstream/data/logs/slipstream.log

# nginx
sudo tail -f /var/log/nginx/error.log /var/log/nginx/access.log
```

More detail:

```ini
LOG_LEVEL=DEBUG
LOG_JSON=true
```

The access log format includes `rt=$request_time urt=$upstream_response_time`, which
distinguishes "the app was slow" from "the client was slow".

---

## Reporting a bug

Include:

1. What you did, what happened, what you expected.
2. Deployment method — Docker, bare metal, Windows — and OS plus architecture.
3. Slipstream version from `/api/health`, and the yt-dlp version.
4. Whether `python -m app.cli verify` passes.
5. Relevant log output. **Redact URLs you would rather not publish, and never paste a
   `SECRET_KEY`, cookie or session token.**
6. For extraction problems, the `yt-dlp -F '<url>'` output.

Confirm you updated yt-dlp first — it fixes most extraction reports.

**Security vulnerabilities do not go in a public issue.** Use a private advisory; see
[SECURITY.md](../SECURITY.md).
