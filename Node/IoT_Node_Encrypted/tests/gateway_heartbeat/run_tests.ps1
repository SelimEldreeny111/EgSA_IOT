param([string]$CompilerPath = 'g++')
$ErrorActionPreference = 'Stop'
$heartbeatNode = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$heartbeatOutput = Join-Path ([IO.Path]::GetTempPath()) ('wiot-gateway-heartbeat-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $heartbeatOutput | Out-Null
foreach ($debugMode in @('off', 'lite', 'full', 'coordinated')) {
    $heartbeatExe = Join-Path $heartbeatOutput ("heartbeat-$debugMode.exe")
    $enabled = ($debugMode -ne 'off').ToString().ToLowerInvariant()
    $lite = ($debugMode -eq 'lite').ToString().ToLowerInvariant()
    $coordinated = [int]($debugMode -eq 'coordinated')
    $raw = ($debugMode -eq 'full').ToString().ToLowerInvariant()
    & $CompilerPath '-std=c++14' '-Wall' '-Wextra' "-DAPP_ENABLE_GATEWAY_HEARTBEAT=$enabled" "-DAPP_ENABLE_DEBUG=$enabled" "-DAPP_DEBUG_LITE=$lite" "-DAPP_DEBUG_REPLY_BYTES=$raw" "-DAPP_LORA_COORDINATED=$coordinated" `
        '-I' (Join-Path $PSScriptRoot 'fakes') '-include' (Join-Path $PSScriptRoot 'fakes/TestAppConfig.h') `
        (Join-Path $heartbeatNode 'src/app/GatewayApp.cpp') (Join-Path $heartbeatNode 'src/comm/ReplyDiagnostics.cpp') (Join-Path $PSScriptRoot 'gateway_heartbeat_test.cpp') '-o' $heartbeatExe
    if ($LASTEXITCODE -ne 0) { throw 'Gateway heartbeat host compile failed' }
    & $heartbeatExe
    if ($LASTEXITCODE -ne 0) { throw 'Gateway heartbeat host check failed' }
}
