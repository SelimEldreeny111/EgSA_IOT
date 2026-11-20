param([string]$Compiler = 'g++')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$output = Join-Path ([System.IO.Path]::GetTempPath()) ('wiot-config-test-' + [guid]::NewGuid().ToString('N') + '.exe')
$compilerPath = (Get-Command $Compiler -ErrorAction Stop).Source
$originalPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $compilerPath) + ';' + $env:PATH
    foreach ($profile in @('loraNode','directWifi','directSim','gatewayWifi')) {
        $flags = @()
        if ($profile -eq 'gatewayWifi') {
            $flags = @('-DAPP_ROLE=2','-DAPP_CONTROLLER_POWER_MODE=0','-DAPP_LORA_POWER_MODE=0')
        } elseif ($profile -eq 'directWifi') {
            $flags = @('-DAPP_UPLINK=1','-DAPP_CONTROLLER_POWER_MODE=0','-DAPP_LORA_POWER_MODE=0')
        } elseif ($profile -eq 'directSim') {
            $flags = @('-DUSE_SIM800','-DAPP_UPLINK=1','-DAPP_CONTROLLER_POWER_MODE=0','-DAPP_LORA_POWER_MODE=0')
        } else {
            $flags = @('-DAPP_UPLINK=2','-DAPP_CONTROLLER_POWER_MODE=3','-DAPP_LORA_POWER_MODE=2')
        }
        & $compilerPath '-std=c++14' '-Wall' '-Wextra' '-Werror' @flags '-I' (Join-Path $PSScriptRoot 'fakes') `
            (Join-Path $root 'src/config/RuntimeConfig.cpp') (Join-Path $root 'src/config/SerialConfig.cpp') `
            (Join-Path $PSScriptRoot 'serial_config_test.cpp') '-o' $output
        if ($LASTEXITCODE) { throw "Compilation failed for $profile" }
        & $output
        if ($LASTEXITCODE) { throw "Tests failed for $profile" }
    }
} finally {
    $env:PATH = $originalPath
    if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output }
}
