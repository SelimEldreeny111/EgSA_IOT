param([string]$Python = 'python', [switch]$SkipDependencyInstall)
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
    Invoke-SimulatorPython @('-m','PyInstaller','--noconfirm','--clean','WIOT_MultiSensor_RS485_Simulator.spec')
    if (!(Test-Path -LiteralPath 'dist/WIOT_MultiSensor_RS485_Simulator.exe')) { throw 'Simulator EXE missing after build' }
    Copy-Item -LiteralPath 'default_config.json' -Destination 'dist\default_config.json' -Force
    Copy-Item -LiteralPath 'stm32_four_sensor_config.json' -Destination 'dist\stm32_four_sensor_config.json' -Force
    Copy-Item -LiteralPath 'README.md' -Destination 'dist\README.md' -Force
    Copy-Item -LiteralPath 'TEST_PLAN.md' -Destination 'dist\TEST_PLAN.md' -Force
    Write-Host ''
    Write-Host 'Build complete:' -ForegroundColor Green
    Write-Host (Resolve-Path 'dist\WIOT_MultiSensor_RS485_Simulator.exe')
}
finally {
    Pop-Location
}
