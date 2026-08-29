<#
.SYNOPSIS
    Run Slipstream on this machine.

.DESCRIPTION
    Starts uvicorn serving both the API and the built SPA on a single port.
    Run scripts\windows\setup.ps1 first.

.EXAMPLE
    .\scripts\windows\start.ps1

.EXAMPLE
    .\scripts\windows\start.ps1 -Port 9000 -Lan
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,

    # Bind 0.0.0.0 so other machines on the network can reach it. This serves
    # session cookies over plain HTTP; only do it on a network you trust.
    [switch]$Lan,

    # Autoreload on source changes. Development only.
    [switch]$Reload,

    # Do not open a browser window.
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend  = Join-Path $RepoRoot 'backend'
$VenvPy   = Join-Path $Backend '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPy)) {
    Write-Host 'The backend virtualenv is missing.' -ForegroundColor Red
    Write-Host 'Run this first:  .\scripts\windows\setup.ps1' -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path (Join-Path $RepoRoot 'frontend\dist\index.html'))) {
    Write-Host 'No SPA bundle at frontend\dist.' -ForegroundColor Yellow
    Write-Host 'Only /api will respond. Build it with:  npm --prefix frontend run build' -ForegroundColor Yellow
    Write-Host ''
}

# Refuse to start on a port already in use rather than letting uvicorn fail
# with a less obvious socket error.
$inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
    $owner = (Get-Process -Id $inUse[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Write-Host "Port $Port is already in use by $owner (PID $($inUse[0].OwningProcess))." -ForegroundColor Red
    Write-Host "Stop it, or choose another port:  .\scripts\windows\start.ps1 -Port 8080" -ForegroundColor Yellow
    exit 1
}

$bindHost = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$url      = "http://localhost:$Port"

Write-Host ''
Write-Host 'Slipstream' -ForegroundColor White
Write-Host "  $url" -ForegroundColor Cyan
if ($Lan) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
           Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
           Select-Object -First 1).IPAddress
    if ($ip) { Write-Host "  http://${ip}:$Port  (LAN)" -ForegroundColor Cyan }
    Write-Host '  LAN mode: traffic is unencrypted. Trusted networks only.' -ForegroundColor Yellow
}
Write-Host '  Ctrl+C to stop.' -ForegroundColor DarkGray
Write-Host ''

if (-not $NoBrowser) {
    # Fire-and-forget after a delay so the browser lands on a listening socket
    # rather than a connection refused page.
    Start-Job -ScriptBlock {
        param($u)
        Start-Sleep -Seconds 3
        Start-Process $u
    } -ArgumentList $url | Out-Null
}

$uvicornArgs = @(
    '-m', 'uvicorn', 'app.main:app',
    '--host', $bindHost,
    '--port', $Port,
    '--timeout-keep-alive', '75'
)
if ($Reload) { $uvicornArgs += '--reload' }

Push-Location $Backend
try {
    & $VenvPy @uvicornArgs
} finally {
    Pop-Location
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host 'Slipstream stopped.' -ForegroundColor DarkGray
}
