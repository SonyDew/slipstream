===============================================================================
 SLIPSTREAM ON WINDOWS
===============================================================================

Slipstream is a self-hosted media downloader. You paste a public media URL, it
shows you the formats that genuinely exist for that item, and streams the file
back to your browser.

This file covers running it on a Windows PC. Nothing here needs a server.


-------------------------------------------------------------------------------
 WHAT YOU NEED FIRST
-------------------------------------------------------------------------------

1. Python 3.11 or newer
   https://www.python.org/downloads/
   IMPORTANT: on the first installer screen, tick
   "Add python.exe to PATH". If you miss it, the setup script cannot find
   Python and you will need to reinstall or add it to PATH by hand.

2. Node.js 20 or newer
   https://nodejs.org/  (the "LTS" download is correct)

3. FFmpeg - the setup script downloads this for you. You do not need to
   install it yourself.

You do NOT need Docker, a web server, or a domain name.


-------------------------------------------------------------------------------
 SETUP (ONCE)
-------------------------------------------------------------------------------

Open PowerShell in this folder. The easiest way: click the address bar in File
Explorer, type  powershell  and press Enter.

Then run:

    .\scripts\windows\setup.ps1

If PowerShell refuses with a message about "running scripts is disabled",
run this once and then try again:

    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

Setup takes a few minutes. It will:
  - check your Python and Node versions
  - install the Python packages into backend\.venv
  - download FFmpeg into .tools\bin
  - build the web interface
  - create a .env file with a generated secret key
  - print your admin username and password

WRITE DOWN THE ADMIN PASSWORD IT PRINTS. It is also saved in the .env file in
this folder. You will be asked to change it after your first sign-in - the
account cannot change any settings until you do.


-------------------------------------------------------------------------------
 STARTING IT
-------------------------------------------------------------------------------

    .\START_WINDOWS.ps1

Your browser opens at http://localhost:8000 automatically.

To stop it, click the PowerShell window and press Ctrl+C.

Other options:

    .\START_WINDOWS.ps1 -Port 8080      use a different port
    .\START_WINDOWS.ps1 -NoBrowser      do not open a browser
    .\START_WINDOWS.ps1 -Lan            let other devices on your network in

About -Lan: this makes Slipstream reachable from your phone or another PC at
http://YOUR-PC-IP:8000. The connection is NOT encrypted, so only do this on a
home or office network you trust, never on public Wi-Fi.


-------------------------------------------------------------------------------
 STARTING AUTOMATICALLY AT BOOT
-------------------------------------------------------------------------------

Optional. Right-click PowerShell, choose "Run as administrator", then:

    .\scripts\windows\install-service.ps1

Slipstream will start with Windows and restart itself if it crashes. It runs in
the background with no window.

To undo it:

    .\scripts\windows\install-service.ps1 -Remove


-------------------------------------------------------------------------------
 KEEPING IT WORKING
-------------------------------------------------------------------------------

Sites change how their players work, and the extraction library has to keep up.
If downloads that used to work start failing, this is almost always why.

The fix, most of the time:

    .\scripts\windows\update.ps1 -YtDlpOnly

That takes seconds. Restart Slipstream afterwards.

Once a month, run the full update, which also backs up your database first:

    .\scripts\windows\update.ps1


-------------------------------------------------------------------------------
 BACKUPS
-------------------------------------------------------------------------------

    .\scripts\windows\backup.ps1

Writes a zip into backups\ containing your database, logs, and .env. Keeps the
last 7 by default.

Stop Slipstream before backing up if you can - the backup is taken safely
either way, but it is one less thing to think about.

The zip contains password hashes and your secret key. Treat it like a password
file: do not email it to yourself or drop it in a shared folder.


-------------------------------------------------------------------------------
 WHEN SOMETHING GOES WRONG
-------------------------------------------------------------------------------

"running scripts is disabled on this system"
    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

"Python was not found"
    Python is installed but not on PATH. Reinstall it and tick
    "Add python.exe to PATH" on the first screen.

"Port 8000 is already in use"
    Something else has the port. Use another one:
    .\START_WINDOWS.ps1 -Port 8080

The page loads but says the API is unreachable
    The server stopped. Look at the PowerShell window for an error, or check
    the log:
    Get-Content data\logs\slipstream.log -Tail 40

A specific site fails to download
    Update the extraction library:
    .\scripts\windows\update.ps1 -YtDlpOnly

Video downloads have no sound, or MP3 is unavailable
    FFmpeg is missing. Re-run setup:
    .\scripts\windows\setup.ps1 -Force

I forgot the admin password
    cd backend
    .\.venv\Scripts\python -m app.cli reset-password --username admin

More detail: docs\TROUBLESHOOTING.md and docs\WINDOWS.md


-------------------------------------------------------------------------------
 WHAT IT WILL NOT DO
-------------------------------------------------------------------------------

Slipstream only downloads media that is publicly accessible. It cannot and will
not get past a paywall, a private account, a login screen, an age gate, or DRM.
That is a deliberate design decision, not a missing feature.

You are responsible for respecting the terms of the sites you use it on and the
copyright law where you live.


-------------------------------------------------------------------------------
 WHERE THINGS LIVE
-------------------------------------------------------------------------------

  .env                     your settings, including the secret key
  data\db\slipstream.db    the database
  data\logs\               log files
  backups\                 backup archives
  scripts\windows\         the scripts described above
  docs\                    fuller documentation

Slipstream is free software under the AGPL-3.0-or-later licence. See LICENSE.
