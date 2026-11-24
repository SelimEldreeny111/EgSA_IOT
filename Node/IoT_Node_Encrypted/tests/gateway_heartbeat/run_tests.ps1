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

foreach ($nodeCount in @(2, 8, 32)) {
    $roster = 1..$nodeCount -join ','
    $trafficExe = Join-Path $heartbeatOutput ("traffic-$nodeCount.exe")
    $trafficArgs = @('-std=c++14', '-Wall', '-Wextra', '-Werror', '-DAPP_LORA_COORDINATED=1',
        '-DAPP_ENABLE_GATEWAY_HEARTBEAT=false', "-DAPP_LORA_COORDINATED_NODES=$roster",
        '-I', (Join-Path $PSScriptRoot 'fakes'), '-include', (Join-Path $PSScriptRoot 'fakes/TestAppConfig.h'),
        (Join-Path $heartbeatNode 'src/app/GatewayApp.cpp'), (Join-Path $PSScriptRoot 'gateway_traffic_test.cpp'),
        '-o', $trafficExe)
    & $CompilerPath @trafficArgs
    if ($LASTEXITCODE -ne 0) { throw "Gateway traffic host compile failed for $nodeCount nodes" }
    & $trafficExe
    if ($LASTEXITCODE -ne 0) { throw "Gateway traffic host check failed for $nodeCount nodes" }
}
