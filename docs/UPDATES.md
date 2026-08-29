# Updates

Keeping an instance current. One dependency matters far more than the rest.

---

## yt-dlp is the only update with a real cadence

Platforms change their players, their signature schemes and their page structure
continuously. yt-dlp keeps up; a months-old copy does not. **The overwhelming majority of "a
site stopped working" reports are fixed by updating yt-dlp**, with no change to Slipstream at
all.

Monthly is a reasonable baseline. Weekly if you rely on fast-moving platforms. Immediately
when something breaks.

Every path has a fast lane for exactly this:

```bash
# Docker
docker compose exec app pip install --upgrade yt-dlp && docker compose restart app

# Bare metal
sudo scripts/linux/update.sh --ytdlp-only

# Windows
.\scripts\windows\update.ps1 -YtDlpOnly
```

The fast lane skips the frontend rebuild and the migrations, so it takes under a minute. A
restart is required either way: the extractor is imported at startup, so a new version is not
picked up by a running process.

Note that the Docker fast lane installs into the running container's filesystem, which a
rebuild discards. It is the right thing when a site is broken *now*; follow up with a proper
image rebuild so the change survives.

### Confirming it worked

```bash
# Docker
docker compose exec app python -c 'import yt_dlp; print(yt_dlp.version.__version__)'

# Bare metal
sudo -u slipstream /opt/slipstream/backend/.venv/bin/python -m pip show yt-dlp | grep Version

# Windows
cd backend; .venv\Scripts\python.exe -m pip show yt-dlp | Select-String Version
```

Then retry the URL that failed.

---

## Full updates

### Docker

```bash
./docker/update.sh
./docker/update.sh -f docker-compose.ubuntu.yml     # with an overlay
```

Backup → `build --pull` → `up -d --remove-orphans` → wait for health → `app.cli verify`.
Extra arguments pass through to `docker compose`, so overlays work as usual.

`--pull` refreshes the base images too, which is where OS-level security fixes and a newer
ffmpeg arrive. Without it you rebuild on a stale base indefinitely.

If the container is not healthy after 90 seconds the script fails and prints the log command
and the rollback path rather than leaving you to work it out. Old images are left in place
deliberately — they are your rollback. Reclaim the space when you are confident:

```bash
docker image prune -f
```

### Bare metal

```bash
sudo scripts/linux/update.sh
sudo scripts/linux/update.sh --skip-backup    # rarely a good idea
sudo scripts/linux/update.sh --skip-git       # you already pulled
```

Backup, `git pull`, rsync into the install directory (excluding `data/`, `.env`, `.venv/`),
refresh pip dependencies, upgrade yt-dlp, `alembic upgrade head`, rebuild the frontend if Node
is present, restart, wait for health, `verify`.

### Windows

```powershell
.\scripts\windows\update.ps1
.\scripts\windows\update.ps1 -YtDlpOnly
.\scripts\windows\update.ps1 -SkipBackup
```

Same sequence.

---

## Unattended yt-dlp refresh

Bare metal has a timer for it:

```bash
sudo systemctl enable --now slipstream-ytdlp-update.timer
sudo systemctl list-timers | grep slipstream
sudo journalctl -u slipstream-ytdlp-update.service
```

Runs on the first of the month at 04:00 with an hour of jitter and `Persistent=true`. Change
`OnCalendar` to `weekly` if you want it more often.

It runs `update.sh --ytdlp-only` deliberately. **An unattended job should not pull new source,
rebuild the frontend, or run migrations** — those are decisions you want to be present for,
and a migration that fails at 04:00 on a schedule is a worse morning than one that fails while
you are watching.

It does restart the app, which drops in-flight downloads. Hence the early hour.

Installed **disabled**, like the backup timer. A scheduled job that restarts your service
should be an explicit choice, not a side effect of running an installer.

For Docker, cron:

```cron
# 04:00 on the 1st: refresh the extractor and restart
0 4 1 * * cd /home/you/slipstream && docker compose exec -T app pip install --upgrade yt-dlp && docker compose restart app
```

---

## Migrations

Applied automatically by `scripts/linux/update.sh` and on container start. Manually:

```bash
# Docker
docker compose exec app python -m alembic upgrade head

# Bare metal
cd /opt/slipstream/backend
sudo -u slipstream .venv/bin/python -m alembic upgrade head
sudo -u slipstream .venv/bin/python -m alembic current
```

**Back up before a migration that comes with a release.** Migrations are forward-only in
practice — a downgrade path exists in the revision file but has had far less testing than the
upgrade, and restoring a backup is the reliable rollback.

---

## Checking for updates

```bash
git fetch && git log --oneline HEAD..origin/main
```

`CHANGELOG.md` records what changed per release, grouped by area. Read it before a version
bump; anything needing operator action is called out there.

Watch the repository releases on GitHub to be notified.

---

## Rolling back

### Docker

The previous image is still on the host:

```bash
docker images slipstream
docker compose down
# pin the old tag in docker-compose.yml, or:
docker tag slipstream:0.1.0 slipstream:latest
docker compose up -d
```

If the update ran a migration, restore the pre-update backup as well — an older application
against a newer schema is not a supported combination:

```bash
./docker/restore.sh backups/slipstream-<pre-update-ts>.tar.gz
```

### Bare metal

```bash
cd /opt/slipstream        # or your source checkout
git log --oneline -10
git checkout <previous-tag>
sudo scripts/linux/install.sh          # idempotent; reinstalls in place
sudo scripts/linux/restore.sh /opt/slipstream/backups/slipstream-<pre-update-ts>.tar.gz
```

`install.sh` is idempotent and does not touch an existing `.env` or database, so it is safe to
re-run against an older checkout.

---

## After any update

```bash
# Docker
docker compose exec app python -m app.cli verify

# Bare metal
cd /opt/slipstream/backend && sudo -u slipstream .venv/bin/python -m app.cli verify

# Windows
cd backend; .venv\Scripts\python.exe -m app.cli verify
```

`verify` checks the schema, the admin account and the toolchain. Then:

1. Load the SPA in a browser — a stale service worker or cached shell shows as a blank page;
   hard-refresh.
2. Analyze a URL and complete one download end to end. This is the only check that exercises
   yt-dlp, ffmpeg and the queue together.
3. `curl -o /dev/null -w '%{http_code}\n' https://your-domain/api/admin/stats` — must still be
   401 or 403.

---

## What to update, and how often

| Component | Cadence | Why |
| --- | --- | --- |
| **yt-dlp** | Monthly, or on breakage | The only one that breaks functionality by ageing |
| Slipstream | Per release | Read `CHANGELOG.md` |
| Base OS packages | Monthly | Security fixes |
| Docker base images | With each rebuild | `--pull` handles it |
| ffmpeg | Rarely | Stable; the OS package is fine |
| Python | Only across major versions | Rebuild the venv when you do |
| Node | Only for a build | Not needed at runtime |

Host packages:

```bash
sudo apt-get update && sudo apt-get upgrade      # Ubuntu
sudo dnf upgrade                                 # Oracle Linux
```

Review pinned Python, npm and Docker dependencies regularly. Update yt-dlp separately: it
changes constantly and each bump can affect which formats a site reports, so test it against
the format-honesty suite before updating other dependencies.

---

## Troubleshooting

**A site broke and updating yt-dlp did not fix it.** Extraction is yt-dlp's job, so check
whether it is a known upstream issue:

```bash
yt-dlp -F '<the url>'      # does yt-dlp itself see formats?
```

If yt-dlp cannot list formats either, the fix belongs upstream — report it at
https://github.com/yt-dlp/yt-dlp/issues. If yt-dlp works and Slipstream does not, that is a
Slipstream bug and worth reporting here with the output of both.

**The update succeeded but the app will not start.**

```bash
# Docker
docker compose logs --tail=100 app

# Bare metal
sudo journalctl -u slipstream -n 100 --no-pager
```

Usual causes: a migration failed halfway, a dependency conflict from a partial pip install, or
`data/` ownership changed. `app.cli verify` narrows it down.

**Sessions all invalidated after an update.** `SECRET_KEY` changed. Check `.env` still has the
original value — if `.env` was recreated, the key is new and every session in the database is
unverifiable. There is no recovery beyond restoring the old key; users just sign in again.

**Blank page after updating.** The browser is holding a cached `index.html` that references
asset hashes which no longer exist. Hard-refresh (Ctrl+Shift+R). The nginx config sets
`no-cache, must-revalidate` on `/` specifically to prevent this, so if it happens repeatedly,
check that the `/` location's `Cache-Control` header survived any edits.

**`alembic upgrade head` fails.** Restore the backup and report it with the error. Do not edit
the `alembic_version` table to make the error go away — that leaves the schema and the
recorded revision disagreeing, which turns every future migration into a new failure.

More in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
