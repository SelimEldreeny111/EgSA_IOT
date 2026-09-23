$ErrorActionPreference = 'Stop'

$simulatorDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location -LiteralPath $simulatorDirectory
try {
    python -m pip install -r requirements.txt
    python -m py_compile multi_sensor_core.py multi_sensor_bus.py multi_sensor_simulator.py
    python -m unittest discover -s tests -v
    python multi_sensor_simulator.py --validate-config default_config.json
    python -m PyInstaller --noconfirm --clean WIOT_MultiSensor_RS485_Simulator.spec
    Copy-Item -LiteralPath 'default_config.json' -Destination 'dist\default_config.json' -Force
    Copy-Item -LiteralPath 'README.md' -Destination 'dist\README.md' -Force
    Copy-Item -LiteralPath 'TEST_PLAN.md' -Destination 'dist\TEST_PLAN.md' -Force
    Write-Host ''
    Write-Host 'Build complete:' -ForegroundColor Green
    Write-Host (Resolve-Path 'dist\WIOT_MultiSensor_RS485_Simulator.exe')
}
finally {
    Pop-Location
}
