<#
.SYNOPSIS
  Runs WIOT Platform v2 as a Windows background service (Task Scheduler) with automatic restart,
  plus a nightly encrypted backup. Run once from an elevated PowerShell (Run as administrator).

.DESCRIPTION
  Creates two scheduled tasks under \WIOT\:
    WIOT Platform  - starts "python -m wiot serve" at boot, restarts it every minute if it stops,
                     no execution time limit (the Task Scheduler default would stop it after 3 days).
    WIOT Backup    - "python -m wiot backup" every night at -BackupTime (default 02:00).
  Both run as SYSTEM in the project folder and read the project's .env file. Remove them with
  uninstall-tasks.ps1. Nothing else on the machine is changed.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-tasks.ps1
  powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-tasks.ps1 -BackupTime 03:30
#>
param(
  [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$BackupTime = "02:00",
  [switch]$NoBackup
)
$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Run this script from an elevated PowerShell (Run as administrator)."
}
$python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python environment not found: $python (create it first, see README)" }
if (-not (Test-Path (Join-Path $ProjectDir ".env"))) { throw ".env not found in $ProjectDir (copy .env.example and set the secrets)" }

$system = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# --- server: at boot, restart on failure, never time out
$serve = New-ScheduledTaskAction -Execute $python -Argument "-m wiot serve" -WorkingDirectory $ProjectDir
$boot = New-ScheduledTaskTrigger -AtStartup
$serveSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskPath "\WIOT\" -TaskName "WIOT Platform" -Action $serve -Trigger $boot `
  -Principal $system -Settings $serveSettings -Description "WIOT Platform v2 server (python -m wiot serve)" -Force | Out-Null
Write-Host "Registered \WIOT\WIOT Platform (starts at boot, restarts every minute if it stops)"

# --- nightly backup
if (-not $NoBackup) {
  $backup = New-ScheduledTaskAction -Execute $python -Argument "-m wiot backup" -WorkingDirectory $ProjectDir
  $nightly = New-ScheduledTaskTrigger -Daily -At $BackupTime
  $backupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
  Register-ScheduledTask -TaskPath "\WIOT\" -TaskName "WIOT Backup" -Action $backup -Trigger $nightly `
    -Principal $system -Settings $backupSettings -Description "Nightly WIOT database backup (python -m wiot backup)" -Force | Out-Null
  Write-Host "Registered \WIOT\WIOT Backup (daily at $BackupTime)"
}

Write-Host ""
Write-Host "Start now:   Start-ScheduledTask -TaskPath '\WIOT\' -TaskName 'WIOT Platform'"
Write-Host "Status:      Get-ScheduledTask -TaskPath '\WIOT\' | Get-ScheduledTaskInfo"
Write-Host "Server log:  $ProjectDir\data\logs\wiot-server.log"
