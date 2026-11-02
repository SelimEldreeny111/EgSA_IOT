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
    $worScheduleCount = 0
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
        & $worCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
            "-DAPP_LORA_WOR_WAKE_SOURCE=$worSource" '-DAPP_LORA_WOR_USE_APP_SCHEDULE=true' `
            '-I' $worFakes '-include' (Join-Path $worFakes 'TestAppConfig.h') `
            (Join-Path $worNodeRoot 'src/power/PowerManager.cpp') `
            (Join-Path $PSScriptRoot 'wor_stop_test.cpp') '-o' $worExecutable
        if ($LASTEXITCODE -ne 0) { throw 'Schedule-driven WOR host build failed' }
        foreach ($worScenario in @('app_independent','app_transmission_only','app_failed_report','app_rate_increase',
            'app_rate_decrease','app_partial_cycle','app_window_deadline','app_millis_wrap',
            'app_rtc_sync','app_rtc_sync_back','app_fractional_stop','app_active_ticks','app_command_wake','app_storage_deadline',
            'app_storage_busy','app_rtc_backward','app_untrusted')) {
            & $worExecutable $worScenario
            if ($LASTEXITCODE -ne 0) { throw "WOR schedule source $worSource scenario failed: $worScenario" }
            $worScheduleCount++
        }
    }
    Write-Host "$worCount production WOR scenarios passed across AUX and UART_RX."
    Write-Host "$worScheduleCount schedule-driven WOR scenarios passed across AUX and UART_RX."
} finally { $env:PATH = $worOriginalPath }
