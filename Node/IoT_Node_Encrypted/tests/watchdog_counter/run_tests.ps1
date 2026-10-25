param([string]$CompilerPath='g++')
$ErrorActionPreference='Stop'
$counterNode=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$counterBuild=Join-Path ([IO.Path]::GetTempPath()) ('wiot-wdt-counter-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $counterBuild | Out-Null
$counterExe=Join-Path $counterBuild 'watchdog_counter_test.exe'
$counterFakes=Join-Path $PSScriptRoot 'fakes'
$counterCompiler=(Get-Command $CompilerPath).Source
$counterOldPath=$env:PATH
try {
    $env:PATH=(Split-Path -Parent $counterCompiler)+';'+$env:PATH
    & $counterCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        '-I' $counterFakes '-include' (Join-Path $counterFakes 'TestAppConfig.h') `
        (Join-Path $counterNode 'src/platform/Watchdog.cpp') `
        (Join-Path $counterNode 'src/platform/WatchdogResetCounter.cpp') `
        (Join-Path $counterNode 'src/platform/PowerResetCounter.cpp') `
        (Join-Path $PSScriptRoot 'watchdog_counter_test.cpp') '-o' $counterExe
    if($LASTEXITCODE -ne 0) { throw 'Watchdog-counter host build failed' }
    foreach($scenario in @('first_normal','first_watchdog','normal_existing','watchdog_existing',
        'disabled_watchdog','saturation','corrupt_normal','corrupt_watchdog','write_failure',
        'preserve_shared_records','duplicate_init','power_on','brownout','pin_reset',
        'software_reset','standby_wake','mixed_iwdg_power','clear_wdt','clear_power',
        'clear_failure','clear_power_failure','power_saturation','power_corrupt','power_write_failure')) {
        & $counterExe $scenario
        if($LASTEXITCODE -ne 0) { throw "Watchdog counter failed: $scenario" }
    }
} finally { $env:PATH=$counterOldPath }
