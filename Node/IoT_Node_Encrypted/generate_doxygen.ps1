<#
.SYNOPSIS
Build the STM32 Arduino firmware HTML and XML API reference.
.DESCRIPTION
Creates the ignored output directory, locates Doxygen, runs the checked-in
Doxyfile, and reports documentation warnings. Run from any working directory.
#>
[CmdletBinding()]
param()

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outputDir = Join-Path $projectDir 'Documentation\Doxygen'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$doxygen = Get-Command doxygen -ErrorAction SilentlyContinue
if ($null -eq $doxygen) {
    $installedDoxygen = 'C:\Program Files\doxygen\bin\doxygen.exe'
    if (Test-Path -LiteralPath $installedDoxygen) {
        $doxygenPath = $installedDoxygen
    } else {
        throw 'Doxygen was not found. Install Doxygen 1.14+ and Graphviz.'
    }
} else {
    $doxygenPath = $doxygen.Source
}

Push-Location -LiteralPath $projectDir
try {
    & $doxygenPath 'Doxyfile'
    if ($LASTEXITCODE -ne 0) {
        throw "Doxygen failed with exit code $LASTEXITCODE."
    }
    $indexPath = Join-Path $outputDir 'html\index.html'
    if (-not (Test-Path -LiteralPath $indexPath)) {
        throw "Doxygen did not create $indexPath."
    }
    $warningPath = Join-Path $outputDir 'warnings.log'
    if ((Test-Path -LiteralPath $warningPath) -and
        (Get-Item -LiteralPath $warningPath).Length -gt 0) {
        Write-Warning "Documentation warnings are recorded in $warningPath."
    }
    Write-Output "Generated $indexPath"
} finally {
    Pop-Location
}
