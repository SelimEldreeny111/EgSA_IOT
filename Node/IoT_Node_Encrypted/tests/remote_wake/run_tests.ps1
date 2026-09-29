param([string]$CompilerPath = 'g++')
$ErrorActionPreference = 'Stop'
$wakeTestRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$wakeTestBuild = Join-Path ([System.IO.Path]::GetTempPath()) ('wiot-wake-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $wakeTestBuild | Out-Null
$wakeTestCompiler = (Get-Command $CompilerPath -ErrorAction Stop).Source
$wakeTestOriginalPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $wakeTestCompiler) + ';' + $env:PATH
    $wakeTestFakes = Join-Path $PSScriptRoot 'fakes'
    $wakeTestExecutable = Join-Path $wakeTestBuild 'remote_wake_test.exe'
    & $wakeTestCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        '-I' $wakeTestFakes '-include' (Join-Path $wakeTestFakes 'TestAppConfig.h') `
        (Join-Path $wakeTestRoot 'src/power/PowerManager.cpp') `
        (Join-Path $wakeTestRoot 'src/comm/CommandHandler.cpp') `
        (Join-Path $PSScriptRoot 'remote_wake_test.cpp') '-o' $wakeTestExecutable
    if ($LASTEXITCODE -ne 0) { throw 'Remote-wake host build failed' }
    & $wakeTestExecutable
    if ($LASTEXITCODE -ne 0) { throw 'Remote-wake host regression failed' }
    & (Join-Path $PSScriptRoot 'test_config.ps1') -CompilerPath $wakeTestCompiler
    Write-Host "Temporary test binary: $wakeTestExecutable"
} finally {
    $env:PATH = $wakeTestOriginalPath
}
