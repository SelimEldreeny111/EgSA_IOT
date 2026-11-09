# One-command local demo on Windows: broker + server + simulated fleet.
# Usage:  powershell -ExecutionPolicy Bypass -File .\run-dev.ps1
# The local broker also bridges the real fleet (Company_1) from the broker the field
# gateways publish to, so live hardware shows next to the simulated demo tenants.
#   -Bridge ""                         run fully offline (simulator only)
#   -BridgeTopic "wiot/Company_1/#","wiot/Company_2/#"   bridge more companies
param(
  [string]$Bridge = "broker.hivemq.com:1883",
  [string[]]$BridgeTopic = @("wiot/Company_1/#")
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q -e ".[analytics,dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - edit secrets, then re-run." ; exit 1 }
$brokerArgs = @("-m","wiot","devbroker")
if ($Bridge) {
  $brokerArgs += @("--bridge", $Bridge)
  foreach ($t in $BridgeTopic) { $brokerArgs += @("--bridge-topic", $t) }
  Write-Host "Bridging $($BridgeTopic -join ', ') from $Bridge"
}
$broker = Start-Process .\.venv\Scripts\python -ArgumentList $brokerArgs -PassThru -WindowStyle Minimized
Start-Sleep 2
$server = Start-Process .\.venv\Scripts\python -ArgumentList "-m","wiot","serve" -PassThru -WindowStyle Minimized
Start-Sleep 4
$sim = Start-Process .\.venv\Scripts\python -ArgumentList "-m","wiot","simulate","--companies","Demo_Utility,Demo_AgriFarm","--report-seconds","5" -PassThru -WindowStyle Minimized
Write-Host "WIOT running at http://127.0.0.1:8000  (Ctrl+C to stop)"
try { while ($true) { Start-Sleep 5 } } finally { $sim, $server, $broker | ForEach-Object { Stop-Process -Id $_.Id -ErrorAction SilentlyContinue } }
