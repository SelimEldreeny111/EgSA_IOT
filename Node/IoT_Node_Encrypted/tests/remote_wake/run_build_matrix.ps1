param(
    [string]$ArduinoCli = 'arduino-cli',
    [string]$ConfigFile = (Join-Path $env:USERPROFILE '.arduinoIDE/arduino-cli.yaml'),
    [string]$BuildRoot = '',
    [string[]]$Profiles = @('normal-sim','remote-sim','remote-wifi','remote-lora',
        'rtc-wifi','rtc-lora','queued-wifi','queued-lora','wor-lora',
        'gateway-wifi','gateway-wor')
)
$ErrorActionPreference = 'Stop'
$wakeBuildNode = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if ($BuildRoot) {
    # Explicitly reuse compiler outputs only; never reset or delete source files.
    $wakeBuildRoot = (Resolve-Path -LiteralPath $BuildRoot -ErrorAction Stop).Path
    if (!(Test-Path -LiteralPath $wakeBuildRoot -PathType Container)) { throw 'BuildRoot must be an existing compiler-output directory' }
} else {
    $wakeBuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('wiot-wake-builds-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $wakeBuildRoot | Out-Null
}
$wakeBuildFqbn = 'STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC'
$wakeBuildFlags = @{
    'normal-sim' = '-DUSE_SIM800 -DAPP_CONTROLLER_POWER_MODE=0';
    'remote-sim' = '-DUSE_SIM800 -DAPP_CONTROLLER_POWER_MODE=2';
    'remote-wifi' = '-DUSE_ESP8266 -DAPP_CONTROLLER_POWER_MODE=2';
    'remote-lora' = '-DUSE_SIM800 -DAPP_UPLINK=2 -DAPP_CONTROLLER_POWER_MODE=2';
    'rtc-wifi' = '-DUSE_ESP8266 -DAPP_CONTROLLER_POWER_MODE=1 -DAPP_WIFI_POWER_MODE=1';
    'rtc-lora' = '-DUSE_SIM800 -DAPP_UPLINK=2 -DAPP_CONTROLLER_POWER_MODE=1 -DAPP_LORA_POWER_MODE=1';
    'queued-wifi' = '-DUSE_ESP8266 -DAPP_CONTROLLER_POWER_MODE=4 -DAPP_WIFI_POWER_MODE=1';
    'queued-lora' = '-DUSE_SIM800 -DAPP_UPLINK=2 -DAPP_CONTROLLER_POWER_MODE=4 -DAPP_LORA_POWER_MODE=1';
    'wor-lora' = '-DUSE_SIM800 -DAPP_UPLINK=2 -DAPP_CONTROLLER_POWER_MODE=3 -DAPP_LORA_POWER_MODE=2';
    'gateway-wifi' = '-DUSE_ESP8266 -DAPP_ROLE=2 -DAPP_CONTROLLER_POWER_MODE=0';
    'gateway-wor' = '-DUSE_ESP8266 -DAPP_ROLE=2 -DAPP_CONTROLLER_POWER_MODE=0 -DAPP_LORA_GATEWAY_WOR_TX=1'
}
$wakeBuildSensors = ' -DAPP_ENABLE_TUF_SENSOR=true -DAPP_ENABLE_HNDA_SENSOR=true -DAPP_ENABLE_SUPMEA_SENSOR=true -DAPP_ENABLE_SONDAS_SENSOR=true'
$wakeBuildToolRoot = Join-Path $env:LOCALAPPDATA 'Arduino15/packages/STMicroelectronics/tools/xpack-arm-none-eabi-gcc'
$wakeBuildObjdump = Get-ChildItem -LiteralPath $wakeBuildToolRoot -Filter 'arm-none-eabi-objdump.exe' -Recurse | Select-Object -First 1 -ExpandProperty FullName
if (-not $wakeBuildObjdump) { throw 'STM32 ARM objdump not found' }
Write-Host "Build outputs: $wakeBuildRoot"
Start-Transcript -Path (Join-Path $wakeBuildRoot 'build-matrix.log') | Out-Null
try {
foreach ($wakeBuildProfile in $Profiles) {
    if (-not $wakeBuildFlags.ContainsKey($wakeBuildProfile)) { throw "Unknown profile: $wakeBuildProfile" }
    $wakeBuildDirectory = Join-Path $wakeBuildRoot $wakeBuildProfile
    Write-Host "Building $wakeBuildProfile (all four sensor drivers)..."
    # Explicitly override all power policies; preserve any live bench settings
    # in the user's AppConfig.h without letting them invalidate other profiles.
    $wakeBuildPolicyFlags = ' -DAPP_LORA_POWER_MODE=0 -DAPP_WIFI_POWER_MODE=0 -DAPP_SIM_POWER_MODE=0'
    if ($wakeBuildProfile -eq 'rtc-wifi') { $wakeBuildPolicyFlags = ' -DAPP_LORA_POWER_MODE=0 -DAPP_SIM_POWER_MODE=0' }
    if ($wakeBuildProfile -eq 'rtc-lora') { $wakeBuildPolicyFlags = ' -DAPP_WIFI_POWER_MODE=0 -DAPP_SIM_POWER_MODE=0' }
    if ($wakeBuildProfile -eq 'queued-wifi') { $wakeBuildPolicyFlags = ' -DAPP_LORA_POWER_MODE=0 -DAPP_SIM_POWER_MODE=0' }
    if ($wakeBuildProfile -eq 'queued-lora' -or $wakeBuildProfile -eq 'wor-lora') { $wakeBuildPolicyFlags = ' -DAPP_WIFI_POWER_MODE=0 -DAPP_SIM_POWER_MODE=0' }
    $wakeBuildArguments = @('compile', '--fqbn', $wakeBuildFqbn,
        '--build-path', $wakeBuildDirectory,
        '--build-property', ('compiler.cpp.extra_flags=' + $wakeBuildFlags[$wakeBuildProfile] + $wakeBuildPolicyFlags + $wakeBuildSensors))
    if (Test-Path -LiteralPath $ConfigFile) { $wakeBuildArguments += @('--config-file', $ConfigFile) }
    & $ArduinoCli @wakeBuildArguments $wakeBuildNode
    if ($LASTEXITCODE -ne 0) { throw "Arduino compile failed: $wakeBuildProfile" }
    $wakeBuildElf = Join-Path $wakeBuildDirectory 'IoT_Node_Encrypted.ino.elf'
    $wakeBuildFlashEnd = [uint64]0
    $wakeBuildSections = @(& $wakeBuildObjdump '-h' $wakeBuildElf)
    for ($wakeBuildSectionIndex = 0; $wakeBuildSectionIndex -lt $wakeBuildSections.Count - 1; $wakeBuildSectionIndex++) {
        if ($wakeBuildSections[$wakeBuildSectionIndex] -match '^\s*\d+\s+\S+\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)' -and
            $wakeBuildSections[$wakeBuildSectionIndex + 1] -match '\bLOAD\b') {
            $wakeBuildSections[$wakeBuildSectionIndex] -match '^\s*\d+\s+\S+\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)' | Out-Null
            $wakeBuildSectionSize = [Convert]::ToUInt64($Matches[1],16)
            $wakeBuildSectionLma = [Convert]::ToUInt64($Matches[2],16)
            if ($wakeBuildSectionLma -ge 0x08000000 -and $wakeBuildSectionLma -lt 0x08040000) {
                $wakeBuildFlashEnd = [Math]::Max($wakeBuildFlashEnd, $wakeBuildSectionLma + $wakeBuildSectionSize)
            }
        }
    }
    if ($wakeBuildFlashEnd -eq 0) { throw "Could not verify flash load sections: $wakeBuildProfile" }
    if ($wakeBuildFlashEnd -ge 0x08020000) { throw "Firmware overlaps reserved EEPROM sector: $wakeBuildProfile" }
    Write-Host ('PASS {0}; flash load ends at 0x{1:X8}, below EEPROM sector 0x08020000' -f $wakeBuildProfile,$wakeBuildFlashEnd)
}
} finally {
    Stop-Transcript | Out-Null
}
