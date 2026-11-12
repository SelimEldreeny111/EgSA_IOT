<#
.SYNOPSIS
  Removes the WIOT scheduled tasks created by install-tasks.ps1 (run as administrator).
  Data, backups and the project folder are not touched.
#>
$ErrorActionPreference = "Stop"
foreach ($name in "WIOT Platform", "WIOT Backup") {
  $task = Get-ScheduledTask -TaskPath "\WIOT\" -TaskName $name -ErrorAction SilentlyContinue
  if ($task) {
    Stop-ScheduledTask -TaskPath "\WIOT\" -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskPath "\WIOT\" -TaskName $name -Confirm:$false
    Write-Host "Removed \WIOT\$name"
  }
}
