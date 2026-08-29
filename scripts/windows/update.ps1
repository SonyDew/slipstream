<#
.SYNOPSIS
    Update Slipstream on this machine.

.DESCRIPTION
    Backs up the database, refreshes dependencies (yt-dlp in particular),
    rebuilds the frontend, and verifies the result.

    yt-dlp is the dependency that matters: platforms change their players
    constantly, so a months-old release simply stops extracting. Running this
    monthly is the maintenance the project actually needs.

.EXAMPLE
    .\scripts\windows\update.ps1

.EXAMPLE
    .\scripts\windows\update.ps1 -YtDlpOnly
#>
[CmdletBinding()]
param(
    # Update only yt-dlp and skip the frontend rebuild. Fast path for "a site
    # stopped working today".
    [switch]$YtDlpOnly,

    [switch]$SkipBackup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend  = Join-Path $RepoRoot 'backend'
$Frontend = Join-Path $RepoRoot 'frontend'
$VenvPy   = Join-Path $Backend '.venv\Scripts\python.exe'

function Write-Step { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "    $m" -ForegroundColor Yellow }

if (-not (Test-Path $VenvPy)) {
    Write-Host 'The backend virtualenv is missing. Run scripts\windows\setup.ps1 first.' -ForegroundColor Red
    exit 1
}

$running = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($running) {
    Write-Warn 'Something is listening on port 8000.'
    Write-Warn 'Stop Slipstream before updating: a live SQLite connection makes the backup unreliable.'
    Write-Host ''
}

# --- Backup ----------------------------------------------------------------
if (-not $SkipBackup) {
    Write-Step 'Backing up the database'
    & (Join-Path $PSScriptRoot 'backup.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed; aborting the update.' }
} else {
    Write-Warn 'backup skipped'
}

# --- yt-dlp ----------------------------------------------------------------
Write-Step 'Updating yt-dlp'
$before = (& $VenvPy -m pip show yt-dlp 2>$null | Select-String '^Version:').ToString()
& $VenvPy -m pip install --upgrade yt-dlp --quiet
if ($LASTEXITCODE -ne 0) { throw 'yt-dlp upgrade failed.' }
$after = (& $VenvPy -m pip show yt-dlp 2>$null | Select-String '^Version:').ToString()
if ($before -eq $after) { Write-Ok "already current ($after)" } else { Write-Ok "$before -> $after" }

if ($YtDlpOnly) {
    Write-Host ''
    Write-Host 'yt-dlp updated. Restart Slipstream to pick it up.' -ForegroundColor Green
    exit 0
}

# --- Python dependencies ---------------------------------------------------
Write-Step 'Refreshing Python dependencies'
& $VenvPy -m pip install -r (Join-Path $Backend 'requirements.txt') `
                         -r (Join-Path $Backend 'requirements-dev.txt') --quiet
if ($LASTEXITCODE -ne 0) { throw 'Dependency refresh failed.' }
Write-Ok 'done'

# --- Migrations ------------------------------------------------------------
Write-Step 'Applying database migrations'
Push-Location $Backend
try {
    & $VenvPy -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'alembic upgrade failed. The app also creates missing tables on boot,'
        Write-Warn 'but check the output above before assuming the schema is correct.'
    } else {
        Write-Ok 'schema current'
    }
} finally {
    Pop-Location
}

# --- Frontend --------------------------------------------------------------
Write-Step 'Rebuilding the frontend'
Push-Location $Frontend
try {
    if (Test-Path 'package-lock.json') { & npm ci } else { & npm install }
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed. The previous dist is still in place.' }
    Write-Ok 'dist rebuilt'
} finally {
    Pop-Location
}

# --- Verify ----------------------------------------------------------------
Write-Step 'Verifying'
Push-Location $Backend
try {
    & $VenvPy -m app.cli verify
    if ($LASTEXITCODE -ne 0) { Write-Warn 'verify reported problems; see above.' } else { Write-Ok 'verify passed' }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Update complete. Start it with .\START_WINDOWS.ps1' -ForegroundColor Green
Write-Host ''
