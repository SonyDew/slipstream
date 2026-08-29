<#
.SYNOPSIS
    Run Slipstream automatically at boot via a Scheduled Task.

.DESCRIPTION
    Registers a task named "Slipstream" that starts the app at system boot and
    restarts it if it exits. Requires an elevated PowerShell session.

    A Scheduled Task is used rather than a real Windows service because the app
    is a plain Python process: turning it into a service would need a wrapper
    like NSSM, which is an extra download for no practical gain here.

    The task runs as SYSTEM so it starts without anyone logging in. That means
    it has no access to per-user PATH entries, so absolute paths are baked in.

.EXAMPLE
    .\scripts\windows\install-service.ps1

.EXAMPLE
    .\scripts\windows\install-service.ps1 -Remove
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,

    # Bind 0.0.0.0 instead of loopback. Unencrypted; trusted networks only.
    [switch]$Lan,

    # Unregister the task instead of creating it.
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TaskName = 'Slipstream'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend  = Join-Path $RepoRoot 'backend'
$VenvPy   = Join-Path $Backend '.venv\Scripts\python.exe'

$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'This script must run elevated.' -ForegroundColor Red
    Write-Host 'Right-click PowerShell and choose "Run as administrator", then re-run it.' -ForegroundColor Yellow
    exit 1
}

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "No scheduled task named '$TaskName'." -ForegroundColor Yellow
        exit 0
    }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed the '$TaskName' scheduled task." -ForegroundColor Green
    Write-Host 'The data directory and .env were left untouched.' -ForegroundColor DarkGray
    exit 0
}

if (-not (Test-Path $VenvPy)) {
    Write-Host 'The backend virtualenv is missing. Run scripts\windows\setup.ps1 first.' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $RepoRoot 'frontend\dist\index.html'))) {
    Write-Host 'No SPA bundle at frontend\dist. Build it before installing the task:' -ForegroundColor Red
    Write-Host '  npm --prefix frontend run build' -ForegroundColor Yellow
    exit 1
}

$bindHost = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }

$action = New-ScheduledTaskAction `
    -Execute $VenvPy `
    -Argument "-m uvicorn app.main:app --host $bindHost --port $Port --timeout-keep-alive 75" `
    -WorkingDirectory $Backend

$trigger = New-ScheduledTaskTrigger -AtStartup

# SYSTEM so the task runs with no user logged in. HighestAvailable is not the
# same thing: it still requires a session.
$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId 'SYSTEM' `
    -LogonType ServiceAccount `
    -RunLevel Highest

# ExecutionTimeLimit 0 means no limit: the process is meant to run forever, and
# the default 72-hour cap would kill it. RestartCount covers a crash.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Replacing the existing '$TaskName' task." -ForegroundColor Yellow
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Description 'Slipstream media downloader' | Out-Null

Write-Host "Registered the '$TaskName' scheduled task." -ForegroundColor Green

if ($Lan) {
    # Only opened when explicitly asked for. A loopback-only install needs no
    # firewall rule, and adding one anyway would widen exposure silently.
    $ruleName = 'Slipstream HTTP'
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
            -Action Allow -Protocol TCP -LocalPort $Port -Profile Private | Out-Null
        Write-Host "Opened TCP $Port inbound on the Private profile." -ForegroundColor Green
    }
    Write-Host 'LAN mode serves session cookies over plain HTTP. Trusted networks only.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Starting it now...' -ForegroundColor Cyan
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 6

try {
    $ready = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health/ready" `
                               -UseBasicParsing -TimeoutSec 10
    if ($ready.StatusCode -eq 200) {
        Write-Host "Running: http://localhost:$Port" -ForegroundColor Green
    }
} catch {
    Write-Host 'Not responding yet. Give it a moment, then check:' -ForegroundColor Yellow
    Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName" -ForegroundColor White
    Write-Host '  Get-Content data\logs\slipstream.log -Tail 40' -ForegroundColor White
}

Write-Host ''
Write-Host 'Manage it with:' -ForegroundColor White
Write-Host "  Start-ScheduledTask -TaskName $TaskName" -ForegroundColor DarkGray
Write-Host "  Stop-ScheduledTask  -TaskName $TaskName" -ForegroundColor DarkGray
Write-Host "  .\scripts\windows\install-service.ps1 -Remove" -ForegroundColor DarkGray
Write-Host ''
