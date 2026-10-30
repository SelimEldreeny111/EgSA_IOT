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
    $worScenarios = @('rtc_deadline','stale_pending','aux_after_stop',
        'edge_during_prepare','edge_during_alarm','edge_before_wfi','edge_after_heartbeat',
        'aux_low_before_stop','unexpected_wake','alarm_failure','untrusted',
        'prepare_failure','pending_aux_low','restore_failure','busy','wake_lease','report_failure',
        'retained_rtc_pin','rtc_handle_failure','edge_during_attach',
        'rx_during_prepare','low_during_prepare','edge_after_arm','storage_busy','storage_deadline','storage_sleep_failure','storage_transfer',
        'edge_after_baseline_clear','low_after_baseline_clear','uart_during_alarm')
    $worCount = 0
    foreach ($worSource in @(0,1)) {
        & $worCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
            "-DAPP_LORA_WOR_WAKE_SOURCE=$worSource" `
            '-I' $worFakes '-include' (Join-Path $worFakes 'TestAppConfig.h') `
            (Join-Path $worNodeRoot 'src/power/PowerManager.cpp') `
            (Join-Path $PSScriptRoot 'wor_stop_test.cpp') '-o' $worExecutable
        if ($LASTEXITCODE -ne 0) { throw 'WOR host build failed' }
        $worSelected = $worScenarios + @('uart_after_stop')
        if ($worSource -eq 1) { $worSelected += @('aux_noise','mode_preserved','rx_mode_invalid') }
        foreach ($worScenario in $worSelected) {
            & $worExecutable $worScenario
            if ($LASTEXITCODE -ne 0) { throw "WOR source $worSource scenario failed: $worScenario" }
            $worCount++
        }
    }
    Write-Host "$worCount production WOR scenarios passed across AUX and UART_RX."
} finally { $env:PATH = $worOriginalPath }
