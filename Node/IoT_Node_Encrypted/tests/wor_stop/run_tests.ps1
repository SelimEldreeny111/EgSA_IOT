param([string]$CompilerPath = 'g++')
$ErrorActionPreference = 'Stop'
$worNodeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$worBuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('wiot-wor-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $worBuildRoot | Out-Null
$worCompiler = (Get-Command $CompilerPath -ErrorAction Stop).Source
$worOriginalPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $worCompiler) + ';' + $env:PATH
    $worExecutable = Join-Path $worBuildRoot 'wor_stop_test.exe'
    $worFakes = Join-Path $PSScriptRoot 'fakes'
    & $worCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        '-I' $worFakes '-include' (Join-Path $worFakes 'TestAppConfig.h') `
        (Join-Path $worNodeRoot 'src/power/PowerManager.cpp') `
        (Join-Path $PSScriptRoot 'wor_stop_test.cpp') '-o' $worExecutable
    if ($LASTEXITCODE -ne 0) { throw 'WOR host build failed' }
    $worScenarios = @('rtc_deadline','stale_pending','aux_after_stop',
        'edge_during_prepare','edge_during_alarm','edge_before_wfi','edge_after_heartbeat',
        'aux_low_before_stop','unexpected_wake','alarm_failure','untrusted',
        'prepare_failure','pending_aux_low','restore_failure','busy','wake_lease','report_failure',
        'retained_rtc_pin','rtc_handle_failure','edge_during_attach',
        'rx_during_prepare','low_during_prepare','edge_after_arm',
        'edge_after_baseline_clear','low_after_baseline_clear','uart_during_alarm')
    foreach ($worScenario in $worScenarios) {
        & $worExecutable $worScenario
        if ($LASTEXITCODE -ne 0) { throw "WOR scenario failed: $worScenario" }
    }
    Write-Host "$($worScenarios.Count) production WOR scenarios passed."
} finally { $env:PATH = $worOriginalPath }
