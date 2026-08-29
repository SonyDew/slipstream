<#
.SYNOPSIS
    Back up the Slipstream database and configuration.

.DESCRIPTION
    Writes a timestamped zip to backups\. The database is copied with SQLite's
    online backup API rather than a file copy: in WAL mode the .db, -wal, and
    -shm files are only consistent together, so copying the .db alone can
    produce an archive that restores to a corrupt state.

.EXAMPLE
    .\scripts\windows\backup.ps1

.EXAMPLE
    .\scripts\windows\backup.ps1 -Destination D:\Backups -Keep 10
#>
[CmdletBinding()]
param(
    [string]$Destination,

    # Number of archives to retain; older ones are deleted. 0 keeps everything.
    [int]$Keep = 7
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend  = Join-Path $RepoRoot 'backend'
$VenvPy   = Join-Path $Backend '.venv\Scripts\python.exe'
$DataDir  = Join-Path $RepoRoot 'data'

if (-not $Destination) { $Destination = Join-Path $RepoRoot 'backups' }
if (-not (Test-Path $VenvPy)) { throw 'The backend virtualenv is missing. Run setup.ps1 first.' }

$dbPath = Join-Path $DataDir 'db\slipstream.db'
if (-not (Test-Path $dbPath)) {
    Write-Host "No database at $dbPath - nothing to back up." -ForegroundColor Yellow
    exit 0
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$staging = Join-Path $env:TEMP "slipstream-backup-$stamp"
$archive = Join-Path $Destination "slipstream-$stamp.zip"

Write-Host "==> Backing up to $archive" -ForegroundColor Cyan

try {
    New-Item -ItemType Directory -Force -Path (Join-Path $staging 'db') | Out-Null

    # sqlite3.Connection.backup() is the online snapshot API; it is safe to run
    # against a database another process is writing to.
    $snapshot = Join-Path $staging 'db\slipstream.db'
    $script = @"
import sqlite3, sys
src = sqlite3.connect(r'file:$dbPath?mode=ro', uri=True)
dst = sqlite3.connect(r'$snapshot')
with dst:
    src.backup(dst)
dst.close(); src.close()
"@
    $script | & $VenvPy -
    if ($LASTEXITCODE -ne 0) { throw 'The database snapshot failed.' }
    Write-Host '    database snapshot taken' -ForegroundColor Green

    # Logs are useful for diagnosing a problem after a restore. In-flight
    # downloads under temp\ are not worth archiving.
    $logs = Join-Path $DataDir 'logs'
    if (Test-Path $logs) {
        Copy-Item $logs (Join-Path $staging 'logs') -Recurse -Force
        Write-Host '    logs included' -ForegroundColor Green
    }

    # .env holds SECRET_KEY: losing it invalidates every session, and losing it
    # along with the database means the instance cannot be restored intact.
    $envFile = Join-Path $RepoRoot '.env'
    if (Test-Path $envFile) {
        Copy-Item $envFile (Join-Path $staging 'env.backup') -Force
        Write-Host '    .env included (contains SECRET_KEY and credentials)' -ForegroundColor Green
    }

    Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $archive -Force
    $sizeMb = [math]::Round((Get-Item $archive).Length / 1MB, 2)
    Write-Host "==> Wrote $archive ($sizeMb MB)" -ForegroundColor Green
} finally {
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
}

if ($Keep -gt 0) {
    $old = Get-ChildItem $Destination -Filter 'slipstream-*.zip' |
           Sort-Object LastWriteTime -Descending |
           Select-Object -Skip $Keep
    foreach ($f in $old) {
        Remove-Item $f.FullName -Force
        Write-Host "    pruned $($f.Name)" -ForegroundColor DarkGray
    }
}

Write-Host ''
Write-Host 'This archive contains password hashes, session records, and your' -ForegroundColor Yellow
Write-Host 'SECRET_KEY. Store it as securely as the instance itself.' -ForegroundColor Yellow
Write-Host ''
