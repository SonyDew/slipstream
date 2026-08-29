# Deployment

Choosing a deployment target, and the Docker path in detail. Platform-specific guides:
[WINDOWS.md](WINDOWS.md), [UBUNTU.md](UBUNTU.md), [ORACLE.md](ORACLE.md).

---

## Which target

| Situation | Use | Guide |
| --- | --- | --- |
| Your own PC, for yourself | Windows scripts | [WINDOWS.md](WINDOWS.md) |
| A rented x86_64 VPS with a domain | Ubuntu + Docker + nginx | [UBUNTU.md](UBUNTU.md) |
| Oracle Cloud Always-Free ARM | Oracle + Docker + nginx | [ORACLE.md](ORACLE.md) |
| Any Docker host, LAN only | this page, base compose | |
| A Linux host, no Docker | `scripts/linux/install.sh` + systemd | this page |

---

## Non-negotiables

Four things must be true of any deployment that is reachable from the internet.

**`SECRET_KEY` must be set and persistent.** It signs sessions. If it changes, every
session is invalidated; if it is empty, the app refuses to start in production. The
entrypoint does not silently generate one per boot, because that would log everyone out on
every restart and look like a mysterious bug rather than a configuration error.

```bash
python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

**TLS, or no public exposure.** The session cookie travels on every request. Over plain
HTTP anyone on the path reads it and is then signed in as that user. Either terminate TLS
(nginx + certbot, as both proxy guides do) or keep the instance on a LAN or a tunnel.

**`COOKIE_SECURE=true` once you have TLS.** Without it the cookie is sent over plain HTTP
too, which discards most of the benefit. It defaults from `ENVIRONMENT` but set it
explicitly behind a proxy, because the app sees plain HTTP from the proxy and cannot infer
that the outside edge was encrypted.

**`TRUSTED_PROXY_COUNT` must equal the number of proxies you actually control.** At `0`
behind a proxy, every client appears to come from the proxy's address, so one user exhausts
everyone's rate limit. Set higher than reality and a client can forge `X-Forwarded-For` to
reset its own counter at will. One nginx in front means `1`. No proxy means `0`.

Then change the seeded admin password. Until you do, that account can read the admin panel
but not mutate anything — deliberate, so a forgotten default is not also a write-capable
default.

---

## Exactly one worker

The job queue and the cleanup loop live in the application process. Two workers means two
queues: a job submitted to worker A is invisible to worker B, so status polls return 404
and jobs appear to vanish. Two cleanup loops also race over the same temp tree.

The constraint is enforced in three places — `docker/entrypoint.sh` overrides
`WEB_CONCURRENCY` and logs why, the systemd unit hardcodes `--workers 1`, and both carry
the reason in a comment. Leave all three alone.

**Scale with `MAX_CONCURRENT_DOWNLOADS`**, which raises parallelism inside the single
process. Downloads are I/O-bound so this works well, and the CPU-bound part is ffmpeg,
which is a subprocess and uses other cores anyway.

---

## Docker

### Layout

```
Dockerfile                  three stages: frontend build → deps → runtime
docker-compose.yml          base: app only, published on 127.0.0.1:8000
docker-compose.dev.yml      overlay: hot reload, bind mounts, Vite container
docker-compose.ubuntu.yml   overlay: + nginx, TLS, x86_64
docker-compose.oracle.yml   overlay: + nginx, TLS, arm64, free-tier tuning
docker/entrypoint.sh        serve | verify | cli | passthrough
docker/build.sh             multi-arch buildx
docker/backup.sh            online SQLite backup + data archive
docker/restore.sh           validated restore
docker/update.sh            backup → rebuild → restart → verify
```

Overlays are additive. Always pass the base file first:

```bash
docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d
```

### Base deployment

```bash
cp .env.example .env
# set SECRET_KEY, and INITIAL_ADMIN_PASSWORD if you want to choose it
docker compose up -d
docker compose logs -f app
```

The base file publishes on **`127.0.0.1:8000`**, not `0.0.0.0`. It has no TLS, so binding
publicly would put session cookies on the wire in plain text. To reach it from your LAN
knowing that, override the mapping:

```yaml
# docker-compose.override.yml
services:
  app:
    ports: ["0.0.0.0:8000:8000"]
```

Do not do that on a public address.

### The image

Three stages, for a reason each:

1. **frontend** — `node:20-bookworm-slim`, `npm ci`, `npm run build`. Because `build` runs
   `tsc -b` first, a type error fails the image build rather than shipping a stale bundle.
   Verified with `test -f dist/index.html`.
2. **deps** — installs `build-essential` and `libffi-dev` into `/opt/venv`. Needed for
   `argon2-cffi` on arm64, where fewer prebuilt wheels exist. The compiler stays in this
   stage and never reaches the runtime image.
3. **runtime** — `python:3.12-slim` plus ffmpeg, ca-certificates, curl and tini. Copies
   `/opt/venv` and the built `dist/`. Runs as uid/gid **10001** (`slipstream`).

`tini` is the entrypoint because the worker spawns ffmpeg and yt-dlp subprocesses. Without
a real init to reap them, cancelled jobs accumulate as zombies until the process table
fills.

`HEALTHCHECK` polls `/api/health/ready` every 30s with a 20s start period.

### Multi-arch build

```bash
./docker/build.sh                                    # native
PLATFORMS=linux/amd64,linux/arm64 ./docker/build.sh  # both
PLATFORMS=linux/arm64 ./docker/build.sh --push
```

Uses a dedicated `slipstream-builder` buildx instance. `--load` only works for a single
architecture — Docker cannot load a manifest list into the local daemon — so a multi-arch
build without `--push` stays in the build cache.

Cross-architecture builds go through QEMU and are slow, dominated by the frontend stage. If
you build arm64 on x86 regularly, a native arm64 builder is worth the setup.

### Container operations

```bash
docker compose ps
docker compose logs -f app
docker compose exec app python -m app.cli verify
docker compose exec app python -m app.cli stats
docker compose exec app python -m app.cli reset-password --username admin
docker compose restart app
docker compose down            # keeps the volume
docker compose down -v         # DELETES the database
```

`down -v` removes the named volume and every account, job and history row with it. There is
no undo.

### Updating

```bash
./docker/update.sh
```

Backup → `build --pull` → `up -d --remove-orphans` → wait for health → `app.cli verify`. If
verify fails it prints the rollback path rather than leaving you to work it out.

The dependency that actually needs a cadence is **yt-dlp**. Platforms change their players
constantly, so a months-old build stops extracting. Monthly is about right; see
[UPDATES.md](UPDATES.md).

### Volumes and data

The base file uses a **named volume** (`slipstream-data`), not a bind mount, because the
container runs as uid 10001 and a host directory owned by your user is not writable by it —
the app then fails at startup with a permissions error that is easy to misread.

If you want a bind mount, `chown -R 10001:10001` the host directory first. The entrypoint
checks writability and says exactly this when it fails.

`/tmp` is a tmpfs (1 GiB in the base file). yt-dlp and ffmpeg scratch there, so a crashed
job leaves nothing behind after a restart. On memory-constrained hosts remember tmpfs *is*
RAM — the Oracle overlay drops it to 512 MiB for that reason.

---

## Bare metal with systemd

For a Linux host without Docker.

```bash
sudo scripts/linux/install.sh
```

Creates the `slipstream` system user, installs to `/opt/slipstream`, rsyncs the source
(excluding `data/`, `.venv/`, `.env`, `node_modules/`, `.git/`), builds a venv, builds the
frontend if Node is present, generates `.env` with a `SECRET_KEY` at mode 600, installs the
systemd unit, starts it, waits for health, and runs `verify`. It prints the generated
credentials once.

Idempotent: re-running upgrades in place without touching an existing `.env` or database.

Overridable: `INSTALL_DIR`, `SERVICE_USER`, `PORT`, `BIND_HOST`. The proxy deploy scripts
call it with `BIND_HOST=127.0.0.1` so the app is not directly reachable.

It handles apt and dnf, including EPEL and RPM Fusion for ffmpeg on Oracle Linux. The
frontend build is skipped when `frontend/dist/index.html` already exists, so you can build
the SPA elsewhere and ship it.

### The unit

`deploy/linux/systemd/slipstream.service`, templated on install:

- `Type=exec`, `--workers 1`
- `KillSignal=SIGINT` so uvicorn shuts down gracefully
- `StartLimitBurst=5` / `StartLimitIntervalSec=300` — a crash loop stops rather than
  hammering the host
- `ProtectSystem=strict` with `ReadWritePaths=<install>/data`
- `PrivateTmp`, `NoNewPrivileges`, `ProtectHome`, `ProtectKernelTunables`
- `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`
- `SystemCallFilter=@system-service` and `~@privileged @obsolete @resources`
- `MemoryMax=2G`, `CPUQuota=200%`, `TasksMax=256`

`MemoryDenyWriteExecute` is deliberately **not** set. CPython's ctypes and several compiled
wheels map writable-executable pages; enabling it makes the interpreter fail at import.

```bash
sudo systemctl status slipstream
sudo journalctl -u slipstream -f
sudo systemctl restart slipstream
```

### Optional timers

Four units are installed but left **disabled**:

```bash
sudo systemctl enable --now slipstream-backup.timer        # 03:30 daily, jittered
sudo systemctl enable --now slipstream-ytdlp-update.timer  # monthly, 04:00
```

Disabled by default on purpose: an unattended job that restarts the app or writes to disk on
a schedule should be an explicit choice, not a side effect of running an installer.

The backup timer uses `RandomizedDelaySec=1800` (so a fleet does not stampede) and
`Persistent=true` (so a missed run happens after boot). It is deliberately **not**
`After=slipstream.service` — the online backup API works against a running database, and
ordering it after the service would make the backup wait on a failed start.

The yt-dlp timer runs `update.sh --ytdlp-only`. An unattended job should not pull new
source, rebuild the frontend, or run migrations; that is a change you want to be present
for.

### Bare-metal operations

```bash
sudo scripts/linux/backup.sh
sudo scripts/linux/backup.sh /mnt/backups
KEEP=30 sudo scripts/linux/backup.sh
sudo scripts/linux/restore.sh /opt/slipstream/backups/slipstream-<ts>.tar.gz
sudo scripts/linux/update.sh
sudo scripts/linux/update.sh --ytdlp-only
```

---

## Reverse proxy

Both proxy guides use the same nginx config. Structure:

```
nginx/nginx.conf                            http-level: logging, limits, gzip, zones
nginx/snippets/security-headers.conf        CSP and friends
nginx/snippets/proxy.conf                   forwarded headers, timeouts
nginx/templates/slipstream.conf.template    TLS + HTTP redirect
nginx/templates-http/slipstream.conf.template   plain HTTP, LAN/tunnel only
```

Three things about this config that will bite you if you edit it without knowing:

**Only files under `/etc/nginx/templates` pass through envsubst.** That is the
`nginx:alpine` entrypoint's behaviour. A `${VAR}` anywhere else reaches nginx unexpanded and
fails to parse. This is why the `upstream` block lives in the templates rather than in
`nginx.conf` — it needs `${SLIPSTREAM_UPSTREAM}`.

**Any `add_header` in a `location` replaces the entire inherited set.** Not adds to —
replaces. So the `/assets/` and `/` locations, which set their own `Cache-Control`,
re-include `security-headers.conf` explicitly. Without that line every asset response
silently loses the CSP and HSTS.

**`upgrade-insecure-requests` is deliberately absent from the CSP.** It would break the
plain-HTTP deployment, where the browser would rewrite every `/assets/` request to `https://`
against a server with no certificate. On the TLS deployment HSTS already forces the upgrade,
so it would add nothing.

### Locations

| Location | Treatment |
| --- | --- |
| `~ ^/api/auth/(login\|register\|change-password)$` | `slipstream_auth` zone, 10 r/m |
| `~ ^/api/jobs/[^/]+/file$` | buffering off, 3600s read timeout, ranges forced |
| `^~ /api/health` | unlimited, `access_log off` |
| `^~ /api/` | `slipstream_api` zone, 30 r/m, burst 20 |
| `^~ /assets/` | `expires 1y`, immutable, headers re-included |
| `/` | `no-cache, must-revalidate`, headers re-included |

The file endpoint is the one that matters most. With `proxy_buffering on` — the default —
nginx tries to buffer a 2 GiB response to disk before sending a byte, which either stalls the
download for minutes or fills `/var/cache/nginx`.

`client_max_body_size` is `1m`, which is correct: requests are small JSON bodies. Downloads
are *responses* and are unaffected.

`proxy_next_upstream error timeout` and nothing more. Analysis and job submission are not
idempotent — a silent retry creates duplicate jobs.

### Rate-limit zones

Defined at the http level in `nginx.conf`:

| Zone | Rate |
| --- | --- |
| `slipstream_api` | 30 r/m |
| `slipstream_auth` | 10 r/m |
| `slipstream_static` | 300 r/m |
| `slipstream_conn` | connection limiting |

This is a second layer, independent of the application's own limits. nginx's is per-IP and
cheap; the app's is per-identity and aware of who is signed in.

On bare metal the zone directives go in `conf.d/slipstream-limits.conf` (Ubuntu) or
`00-slipstream-limits.conf` (Oracle) — numbered so zones are defined before the server block
references them.

---

## Configuration reference

Full list with rationale in `.env.example`. The ones that matter most:

| Variable | Notes |
| --- | --- |
| `SECRET_KEY` | Required in production. Persistent. |
| `ENVIRONMENT` | `production` enables the safe defaults |
| `APP_URL`, `DOMAIN` | Used in generated links |
| `COOKIE_SECURE` | `true` behind TLS |
| `TRUSTED_PROXY_COUNT` | Exactly your proxy depth |
| `DATA_DIR` | Everything mutable lives here |
| `MAX_FILE_SIZE` | Bytes. Default 2 GiB |
| `MAX_VIDEO_DURATION` | Seconds. Default 3 hours |
| `MAX_CONCURRENT_DOWNLOADS` | The scaling knob |
| `TEMP_FILE_TTL` | How long a finished file stays downloadable |
| `CLEANUP_INTERVAL` | Sweep frequency |
| `FFMPEG_PATH`, `FFPROBE_PATH` | Absolute paths if not on `PATH` |
| `LOG_JSON` | `true` for structured logs |

Many limits are also runtime-editable in the admin panel, where a database value overrides
the environment. Secrets and paths are environment-only, so a compromised admin account
cannot rewrite the secret key or repoint the database.

---

## Sizing

| Host | Concurrency | Notes |
| --- | --- | --- |
| 1 vCPU / 1 GB | 1 | Works. 4K muxing will be slow. |
| 2 vCPU / 2 GB | 2 | Comfortable for a handful of users. |
| 4 vCPU / 8 GB | 4 | |
| 4 OCPU / 24 GB (Oracle free) | 3–4 | ARM; the overlay tunes this. |

The bottleneck is almost always ffmpeg CPU during muxing, not bandwidth or memory.

Disk: the database is small (megabytes). `data/temp/` is the variable, and its ceiling is
roughly `MAX_CONCURRENT_DOWNLOADS × MAX_FILE_SIZE`, plus whatever finished files are still
inside their TTL. The Oracle overlay caps `MAX_FILE_SIZE` at 2 GiB with a 1-hour TTL because
the free tier's boot volume is 50 GB total and a full disk takes the database down with it.

---

## After deploying

1. `python -m app.cli verify` — schema, admin account, toolchain.
2. `curl https://your-domain/api/health` — should be JSON.
3. Load `/` in a browser — should be the SPA, not JSON.
4. Sign in and change the admin password. Admin mutations stay locked until you do.
5. `curl -o /dev/null -w '%{http_code}\n' https://your-domain/api/admin/stats` — must be
   401 or 403.
6. Analyze a real URL and complete one download end to end.
7. Set up backups: [BACKUPS.md](BACKUPS.md).
8. Read the hardening checklist in [SECURITY.md](../SECURITY.md).

If something is wrong, [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
