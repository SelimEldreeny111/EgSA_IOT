param([string]$CompilerPath = 'g++')
$ErrorActionPreference = 'Stop'
$valveBuild = Join-Path ([IO.Path]::GetTempPath()) ('wiot-valve-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $valveBuild | Out-Null
$valveCompiler = (Get-Command $CompilerPath).Source
$valveOriginalPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $valveCompiler) + ';' + $env:PATH
    $valveExe = Join-Path $valveBuild 'valve.exe'
    & $valveCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        '-I' (Join-Path $PSScriptRoot 'fakes') '-include' (Join-Path $PSScriptRoot 'fakes/TestAppConfig.h') `
        (Join-Path $PSScriptRoot 'valve_test.cpp') '-o' $valveExe
    if ($LASTEXITCODE -ne 0) { throw 'Valve host build failed' }
    foreach ($valveCase in @('disabled','uncommissioned','open_close','inverted','restore_open',
        'interrupted','corruption','pre_write_failure','post_write_failure','missing_timer',
        'premature_timer','arm_latency','foreground_stall','millis_wrap')) {
        & $valveExe $valveCase
        if ($LASTEXITCODE -ne 0) { throw "Valve regression failed: $valveCase" }
    }
    $valveConfigs = @(
        @{Name='default-sim'; Flags=@('-DUSE_SIM800'); Error=$null},
        @{Name='default-wifi'; Flags=@('-DUSE_ESP8266'); Error=$null},
        @{Name='lora-conflict'; Flags=@('-DUSE_SIM800','-DAPP_UPLINK=2'); Error=$null},
        @{Name='gateway-no-valve'; Flags=@('-DUSE_SIM800','-DAPP_ROLE=2'); Error=$null},
        @{Name='disabled'; Flags=@('-DUSE_SIM800','-DAPP_ENABLE_LATCHING_VALVE=false'); Error=$null},
        @{Name='invalid-enable'; Flags=@('-DUSE_SIM800','-DAPP_ENABLE_LATCHING_VALVE=2'); Error='APP_ENABLE_LATCHING_VALVE must'},
        @{Name='invalid-polarity-confirmation'; Flags=@('-DUSE_SIM800','-DAPP_VALVE_POLARITY_CONFIRMED=2'); Error='APP_VALVE_POLARITY_CONFIRMED must'},
        @{Name='invalid-direction'; Flags=@('-DUSE_SIM800','-DAPP_VALVE_OPEN_AIN1_HIGH=2'); Error='APP_VALVE_OPEN_AIN1_HIGH must'}
    )
    foreach ($valveConfig in $valveConfigs) {
        $valveArgs = @('-std=c++14','-fsyntax-only','-I',(Join-Path $PSScriptRoot 'fakes'))
        $valveArgs += $valveConfig.Flags
        $valveArgs += Join-Path $PSScriptRoot 'config_test.cpp'
        $ErrorActionPreference = 'Continue'
        $valveDiagnostic = (& $valveCompiler @valveArgs 2>&1 | Out-String)
        $valveExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($null -eq $valveConfig.Error) {
            if ($valveExit -ne 0) { throw "Valve real config failed: $($valveConfig.Name): $valveDiagnostic" }
        } elseif ($valveExit -eq 0 -or !$valveDiagnostic.Contains($valveConfig.Error)) {
            throw "Valve real config guard missing: $($valveConfig.Name): $valveDiagnostic"
        }
        Write-Host "PASS valve real AppConfig: $($valveConfig.Name)"
    }
} finally { $env:PATH = $valveOriginalPath }
