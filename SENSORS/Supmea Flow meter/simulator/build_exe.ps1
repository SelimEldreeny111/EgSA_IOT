param([string]$Python = 'python', [switch]$SkipDependencyInstall)
$ErrorActionPreference = 'Stop'
function Invoke-SimulatorPython([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Simulator build step failed: $($Arguments -join ' ')" }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    if (!$SkipDependencyInstall) {
        Invoke-SimulatorPython @('-m','pip','install','-r','requirements.txt')
        Invoke-SimulatorPython @('-m','pip','install','pyinstaller>=6.16,<7')
    }
    Invoke-SimulatorPython @('-m','unittest','discover','-s','tests','-v')
    New-Item -ItemType Directory -Path 'build' -Force | Out-Null
    Invoke-SimulatorPython @('-m','PyInstaller','--noconfirm','--clean','--onefile',
        '--windowed','--name','SUPMEA_FMC240_Simulator','--specpath','build',
        '--collect-data','tzdata',
        'supmea_fmc240_simulator.py')
    if (!(Test-Path -LiteralPath 'dist/SUPMEA_FMC240_Simulator.exe')) { throw 'Simulator EXE missing after build' }
    Copy-Item -LiteralPath 'README.md' -Destination 'dist/README.md' -Force
    $comparisonGuide = Join-Path $PSScriptRoot '../../../Node/IoT_Node_Encrypted/RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md'
    if (Test-Path -LiteralPath $comparisonGuide) {
        Copy-Item -LiteralPath $comparisonGuide -Destination 'dist/RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md' -Force
    }
    Write-Output (Resolve-Path -LiteralPath 'dist/SUPMEA_FMC240_Simulator.exe')
} finally { Pop-Location }
