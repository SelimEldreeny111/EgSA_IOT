param([string]$Python = 'python', [switch]$SkipDependencyInstall,
      [string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'

function Invoke-SimulatorPython([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Simulator build step failed: $($Arguments -join ' ')" }
}

$simulatorDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location -LiteralPath $simulatorDirectory
try {
    if (!$SkipDependencyInstall) { Invoke-SimulatorPython @('-m','pip','install','-r','requirements.txt') }
    Invoke-SimulatorPython @('-m','py_compile','multi_sensor_core.py','multi_sensor_bus.py','multi_sensor_simulator.py')
    Invoke-SimulatorPython @('-m','unittest','discover','-s','tests','-v')
    Invoke-SimulatorPython @('multi_sensor_simulator.py','--validate-config','default_config.json')
    Invoke-SimulatorPython @('-m','PyInstaller','--noconfirm','--clean','--distpath',$OutputDirectory,'WIOT_MultiSensor_RS485_Simulator.spec')
    $simulatorExe = Join-Path $OutputDirectory 'WIOT_MultiSensor_RS485_Simulator.exe'
    if (!(Test-Path -LiteralPath $simulatorExe)) { throw 'Simulator EXE missing after build' }
    Copy-Item -LiteralPath 'default_config.json' -Destination (Join-Path $OutputDirectory 'default_config.json') -Force
    Copy-Item -LiteralPath 'stm32_four_sensor_config.json' -Destination (Join-Path $OutputDirectory 'stm32_four_sensor_config.json') -Force
    Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $OutputDirectory 'README.md') -Force
    Copy-Item -LiteralPath 'TEST_PLAN.md' -Destination (Join-Path $OutputDirectory 'TEST_PLAN.md') -Force
    $referenceGuide = Join-Path $PSScriptRoot '../../Node/IoT_Node_Encrypted/RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md'
    if (Test-Path -LiteralPath $referenceGuide) {
        Copy-Item -LiteralPath $referenceGuide -Destination (Join-Path $OutputDirectory 'RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md') -Force
    }
    Write-Host ''
    Write-Host 'Build complete:' -ForegroundColor Green
    Write-Host (Resolve-Path -LiteralPath $simulatorExe)
}
finally {
    Pop-Location
}
