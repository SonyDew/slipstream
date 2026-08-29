<#
.SYNOPSIS
    One-time setup for running Slipstream on a Windows PC.

.DESCRIPTION
    Checks for Python and Node, creates the backend virtualenv, installs both
    dependency sets, fetches FFmpeg if it is missing, builds the frontend, and
    writes a .env with a generated SECRET_KEY.

    Safe to re-run: existing pieces are reused rather than rebuilt, and an
    existing .env is never overwritten.

.EXAMPLE
    .\scripts\windows\setup.ps1

.EXAMPLE
    .\scripts\windows\setup.ps1 -SkipFFmpeg
#>
[CmdletBinding()]
param(
    # Skip the FFmpeg download. Without ffmpeg the app still runs, but it will
    # honestly report merged video rungs and MP3 conversion as unavailable.
    [switch]$SkipFFmpeg,

    # Reinstall Python and Node dependencies even if they look present.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend  = Join-Path $RepoRoot 'backend'
$Frontend = Join-Path $RepoRoot 'frontend'
$ToolsBin = Join-Path $RepoRoot '.tools\bin'
$VenvPy   = Join-Path $Backend '.venv\Scripts\python.exe'

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "    $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "    $Message" -ForegroundColor Yellow }

Write-Host ''
Write-Host 'Slipstream - Windows setup' -ForegroundColor White
Write-Host '--------------------------' -ForegroundColor DarkGray
Write-Host ''

# --- Prerequisites ---------------------------------------------------------
Write-Step 'Checking prerequisites'

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python was not found on PATH. Install Python 3.11 or newer from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
}

# `python --version` writes to stdout on 3.4+; parse defensively anyway.
$pyVersionRaw = (& python --version 2>&1) -join ' '
if ($pyVersionRaw -notmatch '(\d+)\.(\d+)\.?(\d+)?') {
    throw "Could not parse the Python version from '$pyVersionRaw'."
}
$pyMajor = [int]$Matches[1]
$pyMinor = [int]$Matches[2]
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
    throw "Python 3.11+ is required; found $pyMajor.$pyMinor."
}
Write-Ok "Python $pyMajor.$pyMinor"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    throw "Node.js was not found on PATH. Install Node 20 or newer from https://nodejs.org/."
}
$nodeVersionRaw = (& node --version 2>&1) -join ' '
if ($nodeVersionRaw -notmatch 'v(\d+)') {
    throw "Could not parse the Node version from '$nodeVersionRaw'."
}
$nodeMajor = [int]$Matches[1]
if ($nodeMajor -lt 20) {
    throw "Node 20+ is required; found v$nodeMajor."
}
Write-Ok "Node v$nodeMajor"

# --- Backend virtualenv ----------------------------------------------------
Write-Step 'Setting up the backend virtualenv'

if ((Test-Path $VenvPy) -and -not $Force) {
    Write-Ok 'backend\.venv already exists (use -Force to reinstall)'
} else {
    if (-not (Test-Path $VenvPy)) {
        Push-Location $Backend
        try { & python -m venv .venv } finally { Pop-Location }
        if (-not (Test-Path $VenvPy)) { throw 'Failed to create backend\.venv.' }
        Write-Ok 'created backend\.venv'
    }

    Write-Ok 'installing dependencies (this takes a few minutes)'
    & $VenvPy -m pip install --upgrade pip setuptools wheel --quiet
    if ($LASTEXITCODE -ne 0) { throw 'pip self-upgrade failed.' }

    & $VenvPy -m pip install -r (Join-Path $Backend 'requirements.txt') `
                             -r (Join-Path $Backend 'requirements-dev.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Write-Ok 'Python dependencies installed'
}

# --- FFmpeg ----------------------------------------------------------------
Write-Step 'Checking FFmpeg'

$ffmpegLocal  = Join-Path $ToolsBin 'ffmpeg.exe'
$ffmpegOnPath = Get-Command ffmpeg -ErrorAction SilentlyContinue

if ($ffmpegOnPath) {
    Write-Ok "found on PATH: $($ffmpegOnPath.Source)"
} elseif (Test-Path $ffmpegLocal) {
    Write-Ok "found at .tools\bin\ffmpeg.exe"
} elseif ($SkipFFmpeg) {
    Write-Warn 'skipped. Merged video rungs and MP3 conversion will be unavailable.'
} else {
    Write-Ok 'downloading a static build from gyan.dev (~80 MB)'
    New-Item -ItemType Directory -Force -Path $ToolsBin | Out-Null
    $zip = Join-Path $env:TEMP 'ffmpeg-slipstream.zip'
    $extract = Join-Path $env:TEMP 'ffmpeg-slipstream'

    try {
        # TLS 1.2 is not the default on older PowerShell 5.1 hosts, and the
        # download silently fails without it.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' `
                          -OutFile $zip -UseBasicParsing

        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $extract -Force

        foreach ($exe in @('ffmpeg.exe', 'ffprobe.exe')) {
            $found = Get-ChildItem -Path $extract -Filter $exe -Recurse |
                     Select-Object -First 1
            if (-not $found) { throw "$exe was not present in the archive." }
            Copy-Item $found.FullName (Join-Path $ToolsBin $exe) -Force
        }
        Write-Ok 'ffmpeg.exe and ffprobe.exe installed to .tools\bin'
    } catch {
        Write-Warn "download failed: $($_.Exception.Message)"
        Write-Warn 'Install FFmpeg manually, or re-run with -SkipFFmpeg.'
    } finally {
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- Frontend --------------------------------------------------------------
Write-Step 'Building the frontend'

Push-Location $Frontend
try {
    if ((Test-Path 'node_modules') -and -not $Force) {
        Write-Ok 'node_modules already present (use -Force to reinstall)'
    } else {
        Write-Ok 'installing npm packages'
        if (Test-Path 'package-lock.json') { & npm ci } else { & npm install }
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
    }

    Write-Ok 'building (runs tsc, so type errors stop the build)'
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }

    if (-not (Test-Path (Join-Path $Frontend 'dist\index.html'))) {
        throw 'The build reported success but dist\index.html is missing.'
    }
    Write-Ok 'frontend\dist ready'
} finally {
    Pop-Location
}

# --- .env ------------------------------------------------------------------
Write-Step 'Configuring .env'

$envPath = Join-Path $RepoRoot '.env'
if (Test-Path $envPath) {
    Write-Ok '.env already exists; leaving it untouched'
} else {
    # A generated key means sessions survive restarts. Without it the app
    # invents one per boot in development and logs everyone out on reload.
    $secret = & $VenvPy -c "import secrets; print(secrets.token_urlsafe(64))"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($secret)) {
        throw 'Failed to generate a SECRET_KEY.'
    }

    $adminPassword = & $VenvPy -c @"
import secrets, string
alphabet = string.ascii_letters + string.digits + '-_@#%+='
print(''.join(secrets.choice(alphabet) for _ in range(20)))
"@
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($adminPassword)) {
        throw 'Failed to generate an initial admin password.'
    }

    $ffmpegPath  = if (Test-Path $ffmpegLocal) { Join-Path $ToolsBin 'ffmpeg.exe' } else { 'ffmpeg' }
    $ffprobePath = if (Test-Path $ffmpegLocal) { Join-Path $ToolsBin 'ffprobe.exe' } else { 'ffprobe' }

    $lines = @(
        '# Generated by scripts\windows\setup.ps1',
        '# This file contains credentials. Do not commit it or share it.',
        '',
        'ENVIRONMENT=production',
        "SECRET_KEY=$secret",
        'APP_URL=http://localhost:8000',
        'DOMAIN=localhost',
        '',
        '# Served over plain HTTP on localhost, so the Secure cookie flag is off.',
        '# Set this to true the moment the instance is reachable over HTTPS.',
        'COOKIE_SECURE=false',
        '',
        '# Change this in the app on first sign-in. The seeded account cannot',
        '# perform privileged actions until you do.',
        'INITIAL_ADMIN_USERNAME=admin',
        'INITIAL_ADMIN_EMAIL=admin@localhost',
        "INITIAL_ADMIN_PASSWORD=$adminPassword",
        '',
        "FFMPEG_PATH=$ffmpegPath",
        "FFPROBE_PATH=$ffprobePath",
        '',
        '# A desktop machine is not a server; keep concurrency modest.',
        'MAX_CONCURRENT_DOWNLOADS=2'
    )
    # ASCII avoids the UTF-8 BOM that PowerShell 5.1's default encoding adds,
    # which python-dotenv reads as part of the first variable name.
    Set-Content -Path $envPath -Value $lines -Encoding ASCII

    Write-Ok '.env written with a generated SECRET_KEY'
    Write-Host ''
    Write-Host '    Initial admin credentials' -ForegroundColor White
    Write-Host '      username: admin' -ForegroundColor White
    Write-Host "      password: $adminPassword" -ForegroundColor White
    Write-Host '    Recorded in .env. Change the password after signing in.' -ForegroundColor Yellow
    Write-Host ''
}

# --- Verify ----------------------------------------------------------------
Write-Step 'Verifying the installation'

Push-Location $Backend
try {
    & $VenvPy -m app.cli verify
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'verify reported problems; see the output above.'
    } else {
        Write-Ok 'verify passed'
    }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host ''
Write-Host '  Start it with:  .\START_WINDOWS.ps1' -ForegroundColor White
Write-Host '  Then open:      http://localhost:8000' -ForegroundColor White
Write-Host ''
Write-Host '  Optional: .\scripts\windows\install-service.ps1  (start at boot)' -ForegroundColor DarkGray
Write-Host ''
