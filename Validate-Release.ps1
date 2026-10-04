<#
.SYNOPSIS
Run the STM32 node, Python server, simulator and cross-component release checks.
.DESCRIPTION
Runs from any directory. Never flashes hardware, starts a live server, contacts
an MQTT broker, or reads secret files. Optional firmware builds use local build
configuration; optional simulator packaging uses already-installed dependencies.
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$Compiler = 'g++',
    [string]$NodeJs = 'node',
    [string]$ArduinoCli = 'arduino-cli',
    [switch]$BuildFirmware,
    [switch]$BuildDocumentation,
    [switch]$BuildSimulators
)
$ErrorActionPreference = 'Stop'
$releaseRoot = $PSScriptRoot
$releaseNode = Join-Path $releaseRoot 'Node/IoT_Node_Encrypted'
$releaseServer = Join-Path $releaseRoot 'Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard'
$releaseOutput = Join-Path ([IO.Path]::GetTempPath()) ('wiot-release-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $releaseOutput | Out-Null
foreach ($releaseExecutable in @($Python,$Compiler,$NodeJs)) {
    if (!(Get-Command $releaseExecutable -ErrorAction SilentlyContinue)) {
        throw "Missing dependency: $releaseExecutable. See RELEASE_GUIDE.md."
    }
}
function Invoke-ReleaseNative([string]$Executable,[string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Release check failed: $Executable $($Arguments -join ' ')" }
}
function Invoke-ReleasePythonTests([string]$Directory) {
    Push-Location -LiteralPath $Directory
    try { Invoke-ReleaseNative $Python @('-m','unittest','discover','-s','tests','-p','test_*.py','-v') }
    finally { Pop-Location }
}
Start-Transcript -Path (Join-Path $releaseOutput 'verification.log') | Out-Null
try {
    foreach ($releaseSuite in @('valve','mqtt_priority','network_recovery','watchdog_counter','sensor_availability','rtc_supmea','remote_wake')) {
        Write-Host "Node host suite: $releaseSuite"
        & (Join-Path $releaseNode "tests/$releaseSuite/run_tests.ps1") -CompilerPath $Compiler
        # Scripts throw on failed compiles/tests; do not rely on stale LASTEXITCODE.
    }
    foreach ($releaseSimulator in @('Multi Sensor RS485 Simulator','TUF2000B Flow meter/simulator','Supmea Flow meter/simulator')) {
        Invoke-ReleasePythonTests (Join-Path $releaseRoot "SENSORS/$releaseSimulator")
    }
    Invoke-ReleasePythonTests $releaseServer
    Invoke-ReleaseNative $NodeJs @((Join-Path $releaseServer 'tests/test_sensor_display.js'))
    Invoke-ReleaseNative $NodeJs @((Join-Path $releaseServer 'tests/test_wake_control.js'))
    Invoke-ReleaseNative $NodeJs @((Join-Path $releaseServer 'tests/test_valve_display.js'))
    Push-Location -LiteralPath $releaseRoot
    try { Invoke-ReleaseNative $Python @('-m','unittest','discover','-s','tests/release_audit','-v') }
    finally { Pop-Location }
    if ($BuildDocumentation) { & (Join-Path $releaseNode 'generate_doxygen.ps1') }
    if ($BuildFirmware) {
        & (Join-Path $releaseNode 'tests/remote_wake/run_build_matrix.ps1') -ArduinoCli $ArduinoCli
    }
    if ($BuildSimulators) {
        foreach ($releaseSimulator in @('Multi Sensor RS485 Simulator','TUF2000B Flow meter/simulator','Supmea Flow meter/simulator')) {
            & (Join-Path $releaseRoot "SENSORS/$releaseSimulator/build_exe.ps1") -Python $Python -SkipDependencyInstall
        }
    }
    Write-Host 'PASS: requested release checks completed. Physical hardware acceptance remains required.'
} finally {
    Stop-Transcript | Out-Null
    Write-Host "Verification log: $releaseOutput/verification.log"
}
