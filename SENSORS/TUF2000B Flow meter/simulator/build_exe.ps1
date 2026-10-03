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
    Invoke-SimulatorPython @('-m','unittest','discover','-s','tests','-v')
    Invoke-SimulatorPython @('-m','PyInstaller','--noconfirm','--clean','TUF2000B_Simulator.spec')
    if (!(Test-Path -LiteralPath 'dist/TUF2000B_Simulator.exe')) { throw 'Simulator EXE missing after build' }
    Copy-Item -LiteralPath 'README.md' -Destination 'dist/README.md' -Force
    Write-Output (Resolve-Path -LiteralPath 'dist/TUF2000B_Simulator.exe')
}
finally {
    Pop-Location
}
