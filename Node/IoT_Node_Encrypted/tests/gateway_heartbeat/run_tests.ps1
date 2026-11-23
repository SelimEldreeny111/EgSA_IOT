param([string]$CompilerPath = 'g++')
$ErrorActionPreference = 'Stop'
$heartbeatNode = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$heartbeatOutput = Join-Path ([IO.Path]::GetTempPath()) ('wiot-gateway-heartbeat-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $heartbeatOutput | Out-Null
foreach ($heartbeatEnabled in @('true', 'false')) {
    $heartbeatExe = Join-Path $heartbeatOutput ("heartbeat-$heartbeatEnabled.exe")
    $gatewayDebugEnabled = $heartbeatEnabled
    & $CompilerPath '-std=c++14' '-Wall' '-Wextra' ("-DAPP_ENABLE_GATEWAY_HEARTBEAT=$heartbeatEnabled") ("-DAPP_ENABLE_DEBUG=$gatewayDebugEnabled") `
        '-I' (Join-Path $PSScriptRoot 'fakes') '-include' (Join-Path $PSScriptRoot 'fakes/TestAppConfig.h') `
        (Join-Path $heartbeatNode 'src/app/GatewayApp.cpp') (Join-Path $PSScriptRoot 'gateway_heartbeat_test.cpp') '-o' $heartbeatExe
    if ($LASTEXITCODE -ne 0) { throw 'Gateway heartbeat host compile failed' }
    & $heartbeatExe
    if ($LASTEXITCODE -ne 0) { throw 'Gateway heartbeat host check failed' }
}
