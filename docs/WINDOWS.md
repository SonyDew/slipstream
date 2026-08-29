# Windows

Running Slipstream on a Windows PC — for yourself, on your own machine.

If you are not comfortable in a terminal, read `README_WINDOWS.txt` in the repository root
instead. It covers the same ground in plain language.

---

## What this gives you

The app on `http://127.0.0.1:8000`, serving both the API and the interface from one port.
No Docker, no nginx, no certificates.

**This setup is not for public exposure.** There is no TLS, so session cookies would
travel in plain text. `-Lan` lets other machines on your network reach it, which is fine on
a home network you control and wrong on anything else. For a public instance use
[UBUNTU.md](UBUNTU.md) or [ORACLE.md](ORACLE.md).

---

## Prerequisites

**Python 3.11 or newer** — https://www.python.org/downloads/

Tick **"Add python.exe to PATH"** in the installer. Almost every Windows setup problem
traces back to this box being unticked.

**Node.js 20 or newer** — https://nodejs.org/ (the LTS build). Needed once, to build the
interface.

**FFmpeg** — the setup script downloads it for you into `.tools\bin`. Without it the app
still runs; it just honestly reports merged video rungs and MP3 conversion as unavailable
rather than offering them and failing.

Verify:

```powershell
python --version
node --version
```

---

## Setup

Open PowerShell in the project folder:

```powershell
.\scripts\windows\setup.ps1
```

It checks the prerequisites and their versions, creates the backend virtualenv, installs
both dependency sets, downloads FFmpeg if missing, builds the interface and verifies the
output, writes a `.env` with a generated `SECRET_KEY`, generates a 20-character admin
password, and runs `app.cli verify`.

**The admin username and password are printed once, at the end. Write them down.** They
are in `.env` too, but that file is not meant to be read casually.

Safe to re-run: existing pieces are reused and an existing `.env` is never overwritten.

```powershell
.\scripts\windows\setup.ps1 -SkipFFmpeg   # you already have it, or don't want it
.\scripts\windows\setup.ps1 -Force        # reinstall dependencies anyway
```

### If PowerShell refuses to run the script

```
.\scripts\windows\setup.ps1 : File cannot be loaded because running scripts
is disabled on this system.
```

Windows blocks local scripts by default. Allow them for your account only:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

`RemoteSigned` means locally-written scripts run and downloaded ones need a signature.
`-Scope CurrentUser` avoids changing the machine-wide policy. This is the standard fix, not
a workaround.

---

## Running

```powershell
.\START_WINDOWS.ps1
```

That is a thin launcher over `scripts\windows\start.ps1`, which is worth knowing about
directly:

```powershell
.\scripts\windows\start.ps1                 # 127.0.0.1:8000, opens a browser
.\scripts\windows\start.ps1 -Port 9000
.\scripts\windows\start.ps1 -NoBrowser
.\scripts\windows\start.ps1 -Lan            # reachable from your network
.\scripts\windows\start.ps1 -Reload         # autoreload, development only
```

If the port is already in use it tells you which process owns it rather than failing with a
bare socket error.

Stop it with `Ctrl+C`.

### `-Lan`

Binds `0.0.0.0` so phones and other machines on your network can reach it at
`http://<your-ip>:8000`. The script warns because it is worth warning about: traffic is
unencrypted, so anyone on the network can read session cookies and be signed in as you.

Acceptable on a home network. Not acceptable on shared or public Wi-Fi, and never on an
address reachable from the internet.

Windows Firewall will prompt the first time. `install-service.ps1 -Lan` adds the rule
properly.

---

## First sign-in

Open http://127.0.0.1:8000, sign in with the credentials `setup.ps1` printed, and **change
the password immediately** under Account.

Until you do, the admin account can read the admin panel but cannot change anything — the
account is flagged as using a temporary password. That is deliberate: it means a forgotten
default credential is not also a write-capable one.

---

## Starting at boot

```powershell
# Run as administrator
.\scripts\windows\install-service.ps1
```

This registers a Scheduled Task named **Slipstream** that starts at boot and restarts on
exit. It is a Scheduled Task rather than a real Windows service because the app is a plain
Python process — making it a service needs a wrapper like NSSM, an extra download for no
practical gain.

The task runs as SYSTEM so it starts without anyone logging in. That means it has no access
to per-user `PATH`, which is why absolute paths are baked into the task definition. It also
sets `-ExecutionTimeLimit 0`, because the Task Scheduler's default 72-hour cap would
otherwise kill a long-running server.

```powershell
.\scripts\windows\install-service.ps1 -Lan       # network-reachable, adds a firewall rule
.\scripts\windows\install-service.ps1 -Port 9000
.\scripts\windows\install-service.ps1 -Remove    # unregister
```

Manage it from Task Scheduler, or:

```powershell
Get-ScheduledTask -TaskName Slipstream
Start-ScheduledTask -TaskName Slipstream
Stop-ScheduledTask  -TaskName Slipstream
```

---

## Maintenance

### Updating — the one that matters

```powershell
.\scripts\windows\update.ps1
```

**yt-dlp is the dependency with a real cadence.** Platforms change their players
constantly, so a months-old build stops extracting from sites that worked yesterday.
Monthly is about right. When a site breaks unexpectedly, this is the first thing to try:

```powershell
.\scripts\windows\update.ps1 -YtDlpOnly
```

That skips the frontend rebuild and just refreshes the extractor. Fast, and it fixes the
majority of "a site stopped working today" reports.

The full run backs up first, refreshes pip dependencies, applies migrations, rebuilds the
frontend, and verifies. `-SkipBackup` exists but there is rarely a reason.

### Backups

```powershell
.\scripts\windows\backup.ps1
.\scripts\windows\backup.ps1 -Destination D:\Backups -Keep 10
```

Writes a timestamped zip to `backups\`.

The database is copied with SQLite's **online backup API**, not a file copy. In WAL mode the
`.db`, `-wal` and `-shm` files are only consistent together, so copying the `.db` alone can
produce an archive that restores to a corrupt state. Safe to run while the app is running.

The archive includes `.env`, which contains your `SECRET_KEY`, and the database, which
contains password hashes. **Treat a backup as sensitive** — do not put it in a public cloud
folder without encryption.

More in [BACKUPS.md](BACKUPS.md).

---

## Where things live

```
backend\.venv\             Python virtualenv
frontend\dist\             built interface
data\db\slipstream.db      accounts, jobs, history, settings
data\logs\                 log files
data\temp\                 in-flight and recently finished downloads
backups\                   backup archives
.tools\bin\                downloaded FFmpeg
.env                       configuration, including SECRET_KEY
```

Everything is inside the project folder. Nothing is written to `Program Files`, the
registry, or your user profile. To move the install, move the folder — then re-run
`install-service.ps1` if you had the boot task registered, since it stores absolute paths.

---

## Configuration

`.env` in the project root. Restart to pick up changes.

Common edits:

```ini
MAX_CONCURRENT_DOWNLOADS=4
MAX_FILE_SIZE=4294967296
TEMP_FILE_TTL=14400
REGISTRATION_ENABLED=false
```

Most limits are also editable in the admin panel without a restart, where a database value
overrides the environment. `.env.example` documents every variable.

FFmpeg not being found is the common case for the two path settings:

```ini
FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe
FFPROBE_PATH=C:\ffmpeg\bin\ffprobe.exe
```

---

## Troubleshooting

**"Python was not found"** — not on `PATH`. Reinstall and tick "Add python.exe to PATH", or
add it manually.

**"running scripts is disabled"** — see the `Set-ExecutionPolicy` fix above.

**The page loads but nothing works / only JSON at `/`** — `frontend\dist` is missing. Run
`npm --prefix frontend run build`, or re-run `setup.ps1`.

**No MP3 options, or "FFmpeg is not installed"** — FFmpeg is not on the server process's
`PATH`, which is not always your shell's. Re-run `setup.ps1` without `-SkipFFmpeg`, or set
`FFMPEG_PATH` and `FFPROBE_PATH` to absolute paths.

**A site that used to work now fails** — `.\scripts\windows\update.ps1 -YtDlpOnly`.

**Port already in use** — `start.ps1` names the owning process. Either stop it or use
`-Port`.

**Downloads are very slow** — muxing is CPU-bound. Watch ffmpeg in Task Manager during a
download; if it is pinned, that is the limit. Lower `MAX_CONCURRENT_DOWNLOADS` so jobs
compete less.

**Windows Defender flags something** — yt-dlp and ffmpeg are occasionally false-positived.
Verify what you downloaded came from the official sources, then add an exclusion for the
project folder if you are satisfied.

**I forgot the admin password**

```powershell
cd backend
.venv\Scripts\python.exe -m app.cli reset-password --username admin
```

Omit `--password` to be prompted, which keeps it out of your shell history.

**Is it healthy?**

```powershell
cd backend
.venv\Scripts\python.exe -m app.cli verify
```

More in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Uninstalling

```powershell
.\scripts\windows\install-service.ps1 -Remove   # if you registered the boot task
```

Then delete the project folder. Nothing else on the system was touched.

Copy `data\db\slipstream.db` out first if you want to keep your history.
