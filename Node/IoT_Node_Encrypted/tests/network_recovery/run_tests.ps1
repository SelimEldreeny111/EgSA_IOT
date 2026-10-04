param([string]$CompilerPath='g++')
$ErrorActionPreference='Stop'
$networkTestBuild=Join-Path ([IO.Path]::GetTempPath()) ('wiot-network-recovery-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $networkTestBuild | Out-Null
$networkTestCompiler=(Get-Command $CompilerPath).Source
$networkTestOldPath=$env:PATH
try {
    $env:PATH=(Split-Path -Parent $networkTestCompiler)+';'+$env:PATH
    $networkCommonFakes=Join-Path $PSScriptRoot '../mqtt_priority/fakes'
    foreach($networkMode in @('sim','wifi')) {
        $networkTestExe=Join-Path $networkTestBuild "network_$networkMode.exe"
        $networkFlags=@('-std=c++14','-Wall','-Wextra','-Werror','-pedantic',
            '-I',(Join-Path $PSScriptRoot 'fakes'),'-I',$networkCommonFakes,
            '-include',(Join-Path $PSScriptRoot 'fakes/TestAppConfig.h'),
            (Join-Path $PSScriptRoot 'network_recovery_test.cpp'),'-o',$networkTestExe)
        if($networkMode -eq 'wifi') { $networkFlags += '-DTEST_ESP8266' }
        & $networkTestCompiler @networkFlags
        if($LASTEXITCODE -ne 0) { throw "$networkMode recovery host build failed" }
        $networkCases=@('offline','success_first_stage','success_second_stage','custom_limit')
        if($networkMode -eq 'sim') { $networkCases += 'gprs_offline' }
        else { $networkCases += @('wifi_fallback','wifi_same_fallback') }
        foreach($networkCase in $networkCases) {
            & $networkTestExe $networkCase
            if($LASTEXITCODE -ne 0) { throw "$networkMode recovery failed: $networkCase" }
        }
    }
} finally { $env:PATH=$networkTestOldPath }
