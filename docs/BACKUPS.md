# Backups

What to back up, why the method matters, and how to restore.

---

## Why not just copy the file

The database runs in **WAL mode**. There are three files:

```
data/db/slipstream.db          the main database
data/db/slipstream.db-wal      the write-ahead log
data/db/slipstream.db-shm      the shared-memory index
```

They are only consistent **together**. A committed transaction may live entirely in the
`-wal` file and not yet be in the `.db`. So:

- Copying only the `.db` gives you a database missing every committed-but-not-checkpointed
  transaction. Recent accounts, jobs and settings changes are simply gone.
- Copying all three while the app is writing catches them at different moments, which can
  produce a set that will not open at all.

Every backup path in this repository therefore uses SQLite's **online backup API**:

```python
src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
dst = sqlite3.connect(dst_path)
with dst:
    src.backup(dst)
```

That produces one consistent file while the app keeps serving requests. No downtime, no
locking the writer out.

**Never back this database up with `cp`, `rsync`, a filesystem snapshot of a live volume, or
`docker cp`.** They all have the same flaw. If you use volume snapshots for the host, take
an application-level backup as well.

---

## What is in a backup

| Path | Contents | Sensitivity |
| --- | --- | --- |
| `data/db/slipstream.db` | Accounts, sessions, jobs, history, audit log, settings | **Argon2 password hashes** |
| `data/logs/` | Application logs | Request paths, IP addresses |
| `.env` | Configuration | **`SECRET_KEY`** |
| `data/temp/` | In-flight downloads | Excluded — worthless later |

`.env` is included deliberately. `SECRET_KEY` signs sessions, and restoring a database with
a different key invalidates every session in it. Losing the key alongside the database means
you cannot restore the instance intact.

**Treat a backup archive as being as sensitive as the server.** It holds password hashes and
the signing key. The bare-metal script writes archives at mode 600 for that reason. Do not
put one in an unencrypted cloud folder.

---

## Docker

```bash
./docker/backup.sh                  # → ./backups/slipstream-<ts>.tar.gz
./docker/backup.sh /mnt/backups
CONTAINER=my-slipstream ./docker/backup.sh
```

Runs the online snapshot inside the container using Python's `sqlite3` module — already in
the image, so no extra package — then tars `/app/data` excluding the live database files and
`temp/*`, and removes the snapshot.

Safe against a running container. No downtime.

### Automating it

```bash
sudo crontab -e
```

```cron
# 03:30 daily. Absolute paths: cron's PATH is minimal.
30 3 * * * cd /home/you/slipstream && /home/you/slipstream/docker/backup.sh /mnt/backups >> /var/log/slipstream-backup.log 2>&1
```

Prune old archives yourself — the Docker script does not:

```cron
0 4 * * * find /mnt/backups -name 'slipstream-*.tar.gz' -mtime +30 -delete
```

---

## Bare metal

```bash
sudo scripts/linux/backup.sh
sudo scripts/linux/backup.sh /mnt/backups
KEEP=30 sudo scripts/linux/backup.sh
INSTALL_DIR=/srv/slipstream sudo scripts/linux/backup.sh
```

Writes `<install>/backups/slipstream-<timestamp>.tar.gz` at mode 600, containing the
snapshot, `logs/`, and `.env` as `env.backup`. Keeps the last `KEEP` archives (default 7) and
prunes the rest, using `find -printf | sort` rather than a glob loop so a custom destination
with spaces in the path does not break the prune.

Safe against a live instance.

### The timer

```bash
sudo systemctl enable --now slipstream-backup.timer
sudo systemctl list-timers | grep slipstream
sudo journalctl -u slipstream-backup.service
```

Daily at 03:30 with `RandomizedDelaySec=1800` (so a fleet does not stampede a shared backup
target) and `Persistent=true` (so a run missed while the host was off happens after boot).

Installed **disabled**. An unattended job that writes to disk on a schedule should be an
explicit choice, not a side effect of running an installer.

It is deliberately **not** `After=slipstream.service`. The online backup API works fine
against a running database, and ordering it after the service would make backups wait on a
service that failed to start — exactly when you most want one.

---

## Windows

```powershell
.\scripts\windows\backup.ps1
.\scripts\windows\backup.ps1 -Destination D:\Backups -Keep 10
```

Writes a timestamped zip to `backups\` containing the snapshot, `logs\` and `.env`. Same
online backup API, via a here-string piped to the venv's Python.

Scheduled:

```powershell
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\slipstream\scripts\windows\backup.ps1"'
$trigger = New-ScheduledTaskTrigger -Daily -At 3:30am
Register-ScheduledTask -TaskName 'Slipstream Backup' -Action $action -Trigger $trigger `
  -Description 'Daily Slipstream database backup'
```

---

## Restoring

Restoring **replaces** the current database. Both scripts stop the service first, because
writing under a live SQLite connection corrupts it.

### Docker

```bash
./docker/restore.sh ./backups/slipstream-20260825T033000Z.tar.gz
```

Before touching anything it validates that the file is a readable gzip archive **and** that it
contains `db/slipstream.backup.db`. An archive from somewhere else is refused:

> It was not produced by docker/backup.sh; restoring it would leave the instance without a
> database. Aborting.

That check exists because the failure it prevents is silent. Extracting an unrelated tarball
over a cleared data directory leaves you with no database and no backup to go back to.

Then: requires you to type `restore`, stops the container, clears and extracts the volume via
a throwaway alpine container, renames the snapshot back to `slipstream.db`, removes stale
`-wal` and `-shm` files, `chown -R 10001:10001`, restarts, and waits for health.

### Bare metal

```bash
sudo scripts/linux/restore.sh /opt/slipstream/backups/slipstream-<ts>.tar.gz
```

Same idea, checking for `db/slipstream.db` since the bare-metal archive stores the snapshot
under its final name, and the same typed confirmation. It **moves the current data tree aside**
rather than deleting it:

```
/opt/slipstream/data.pre-restore.20260825T141200Z
```

So a restore that turns out to be the wrong archive is recoverable without a second backup.
Delete that directory once you are satisfied.

It then runs `PRAGMA integrity_check` on the restored database and refuses to finish if it
fails, telling you where the previous tree still is.

The archive's `.env` is written to `.env.restored`, **not over** the live `.env`. If
`SECRET_KEY` differs, every restored session is invalid — compare them and copy it across if
you want the old sessions to keep working. Silently replacing the running configuration
during a restore would be a worse surprise than an extra file.

Stale `-wal` and `-shm` are removed: a restored database must not inherit a write-ahead log
from whatever was there before.

### Windows

No restore script. It is a manual operation, which is appropriate for something this
destructive:

```powershell
# 1. Stop the app (Ctrl+C, or Stop-ScheduledTask -TaskName Slipstream)

# 2. Keep the current state
Rename-Item data data.old

# 3. Extract
Expand-Archive -Path backups\slipstream-<ts>.zip -DestinationPath data

# 4. Remove any stale WAL files
Remove-Item data\db\slipstream.db-wal, data\db\slipstream.db-shm -ErrorAction SilentlyContinue

# 5. Start, then verify
.\START_WINDOWS.ps1
```

---

## Verifying a backup

An untested backup is a hope, not a backup. Check integrity without restoring:

```bash
mkdir -p /tmp/bk && tar -xzf backups/slipstream-<ts>.tar.gz -C /tmp/bk
ls -la /tmp/bk/db/

python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/bk/db/slipstream.db')
print('integrity:', c.execute('PRAGMA integrity_check').fetchone()[0])
print('users:', c.execute('SELECT count(*) FROM users').fetchone()[0])
print('history:', c.execute('SELECT count(*) FROM download_history').fetchone()[0])
c.close()
"

rm -rf /tmp/bk
```

`integrity_check` should print `ok`. A non-zero user count confirms the snapshot caught real
data rather than an empty schema.

Do a full restore into a throwaway instance occasionally. That is the only way to find out
whether your restore procedure actually works, and finding out during an incident is the
expensive way.

---

## A retention policy that is enough

- Daily, keep 7.
- Weekly, keep 4.
- Monthly, keep 3.
- **At least one copy off the host.** A backup on the same disk as the database does not
  survive the failure mode you are most likely to hit.

`KEEP=` handles the bare-metal daily rotation. For weekly and monthly, copy an archive
elsewhere on a schedule:

```cron
# Sunday: promote the newest daily to the weekly set
15 4 * * 0 cp "$(ls -t /opt/slipstream/backups/slipstream-*.tar.gz | head -1)" /mnt/backups/weekly/
```

For off-host, use whatever you already trust — rclone to object storage, `scp` to another
box, a mounted network share. Encrypt if the destination is not yours:

```bash
gpg --symmetric --cipher-algo AES256 backups/slipstream-<ts>.tar.gz
```

---

## What is not worth backing up

**`data/temp/`** — in-flight and recently finished downloads. They expire in hours anyway and
are re-derivable from the source URL. Both scripts exclude it.

**`frontend/dist/`** — build output. Rebuild it.

**`backend/.venv/`** — reinstall from `requirements.txt`, which is pinned.

**The application source** — that is what the repository is for. What is irreplaceable is the
database and `SECRET_KEY`; everything else can be rebuilt from the repo in minutes.

---

## Disaster recovery

Host gone, backup archive in hand:

```bash
# 1. New host, same procedure as originally
git clone <url> slipstream && cd slipstream
sudo scripts/ubuntu/deploy.sh --domain your-domain.com --email you@example.com

# 2. Restore over the fresh install
sudo scripts/linux/restore.sh /mnt/backups/slipstream-<ts>.tar.gz

# 3. Match SECRET_KEY, or every restored session is invalid
sudo diff /opt/slipstream/.env /opt/slipstream/.env.restored
sudo cp /opt/slipstream/.env.restored /opt/slipstream/.env   # if you want old sessions to work
sudo systemctl restart slipstream

# 4. Confirm
cd /opt/slipstream/backend
sudo -u slipstream .venv/bin/python -m app.cli verify
sudo -u slipstream .venv/bin/python -m app.cli stats
```

Step 3 is the one that gets skipped. Without it users are silently logged out and it looks
like the restore lost their accounts, when in fact only their sessions are gone.
