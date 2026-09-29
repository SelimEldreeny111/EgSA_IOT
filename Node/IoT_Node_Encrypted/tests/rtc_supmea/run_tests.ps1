param([string]$CompilerPath = 'g++')

$ErrorActionPreference = 'Stop'
$rtcTestNodeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$rtcTestBuild = Join-Path ([System.IO.Path]::GetTempPath()) ('wiot-rtc-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $rtcTestBuild | Out-Null
$rtcTestExecutable = Join-Path $rtcTestBuild 'rtc_supmea_test.exe'
$rtcTestFakes = Join-Path $PSScriptRoot 'fakes'
$rtcTestCompiler = (Get-Command $CompilerPath -ErrorAction Stop).Source
$rtcTestOriginalPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $rtcTestCompiler) + ';' + $env:PATH
    & $rtcTestCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        '-I' $rtcTestFakes '-include' (Join-Path $rtcTestFakes 'TestAppConfig.h') `
        (Join-Path $rtcTestNodeRoot 'src/devices/RTC.cpp') `
        (Join-Path $rtcTestNodeRoot 'src/app/SupmeaPeriodAccumulator.cpp') `
        (Join-Path $PSScriptRoot 'rtc_supmea_test.cpp') '-o' $rtcTestExecutable
    if ($LASTEXITCODE -ne 0) { throw 'Host regression build failed' }
    $rtcTestScenarios = @(
        'backup_access', 'stime_locked', 'stime_invalid', 'stime_clock_failure',
        'stime_marker_failure', 'stime_stale_marker', 'untrusted_clock', 'baseline_and_backup_recovery',
        'counter_reset', 'flash_failure_retry', 'flash_fallback', 'midnight',
        'new_year', 'cairo_midnight', 'explicit_reset', 'alarm_access'
    )
    foreach ($rtcTestScenario in $rtcTestScenarios) {
        & $rtcTestExecutable $rtcTestScenario
        if ($LASTEXITCODE -ne 0) { throw "Regression failed: $rtcTestScenario" }
    }
    Write-Host "$($rtcTestScenarios.Count) RTC/Supmea regression scenarios passed."
    Write-Host "Temporary test binary: $rtcTestExecutable"
} finally {
    $env:PATH = $rtcTestOriginalPath
}
