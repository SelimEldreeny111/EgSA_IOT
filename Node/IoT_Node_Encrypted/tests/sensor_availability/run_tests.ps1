param([string]$CompilerPath='g++')
$ErrorActionPreference='Stop'
$availabilityRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$availabilityBuild=Join-Path ([IO.Path]::GetTempPath()) ('wiot-availability-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $availabilityBuild | Out-Null
$availabilityCompiler=(Get-Command $CompilerPath -ErrorAction Stop).Source
$availabilityOldPath=$env:PATH
try {
    $env:PATH=(Split-Path -Parent $availabilityCompiler)+';'+$env:PATH
    foreach ($availabilityProfile in 0..3) {
        $availabilityExe=Join-Path $availabilityBuild "availability-$availabilityProfile.exe"
        & $availabilityCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
            '-I' (Join-Path $PSScriptRoot 'fakes') `
            '-include' (Join-Path $PSScriptRoot 'fakes/TestAppConfig.h') `
            "-DTEST_FLOW_CONFIG=$availabilityProfile" `
            (Join-Path $availabilityRoot 'src/app/AppState.cpp') `
            (Join-Path $availabilityRoot 'src/app/FlowMeterManager.cpp') `
            (Join-Path $PSScriptRoot 'sensor_availability_test.cpp') '-o' $availabilityExe
        if ($LASTEXITCODE -ne 0) { throw "Availability build failed: $availabilityProfile" }
        & $availabilityExe
        if ($LASTEXITCODE -ne 0) { throw "Availability regression failed: $availabilityProfile" }
    }
} finally { $env:PATH=$availabilityOldPath }
