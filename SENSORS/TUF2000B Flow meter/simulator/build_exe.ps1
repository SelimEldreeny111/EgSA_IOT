$ErrorActionPreference = 'Stop'

$simulatorDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location -LiteralPath $simulatorDirectory
try {
    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -v
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name TUF2000B_Simulator `
        tuf2000b_simulator.py
}
finally {
    Pop-Location
}
