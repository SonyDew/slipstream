<#
.SYNOPSIS
    Start Slipstream.

.DESCRIPTION
    Convenience launcher. Everything it does lives in scripts\windows\.

    First time here? Run this instead:
        .\scripts\windows\setup.ps1

.EXAMPLE
    .\START_WINDOWS.ps1

.EXAMPLE
    .\START_WINDOWS.ps1 -Port 8080
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Lan,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$start = Join-Path $PSScriptRoot 'scripts\windows\start.ps1'
if (-not (Test-Path $start)) {
    Write-Host 'scripts\windows\start.ps1 is missing. Is this a complete checkout?' -ForegroundColor Red
    exit 1
}

# Nudge toward setup before start.ps1 fails with a less obvious message.
if (-not (Test-Path (Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe'))) {
    Write-Host ''
    Write-Host 'Slipstream is not set up yet.' -ForegroundColor Yellow
    Write-Host 'Run this first:  .\scripts\windows\setup.ps1' -ForegroundColor White
    Write-Host ''
    exit 1
}

& $start -Port $Port -Lan:$Lan -NoBrowser:$NoBrowser
exit $LASTEXITCODE
