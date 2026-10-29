param([string]$CompilerPath = 'g++')
$ErrorActionPreference = 'Stop'
$wakeConfigRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$wakeConfigCompiler = (Get-Command $CompilerPath -ErrorAction Stop).Source
$wakeConfigDefaults = @{
    APP_ROLE = '1'; APP_UPLINK = '1'; APP_CONTROLLER_POWER_MODE = '0';
    APP_LORA_POWER_MODE = '0'; APP_WIFI_POWER_MODE = '0'; APP_SIM_POWER_MODE = '0';
    APP_POWER_SLEEP_SECONDS = '30UL'; APP_POWER_COMMAND_WINDOW_MS = '5000UL';
    APP_REMOTE_WAKE_DEFAULT_SECONDS = '60UL'; APP_REMOTE_WAKE_POLL_INTERVAL_MS = '100UL'
}
$wakeConfigCases = @(
    @{Name='remote-app-schedule'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_REMOTE_WAKE_USE_APP_SCHEDULE='true'}; Error=$null},
    @{Name='remote-legacy-cycle'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_REMOTE_WAKE_USE_APP_SCHEDULE='false'}; Error=$null},
    @{Name='reject-invalid-remote-schedule'; Modem='USE_SIM800'; Defines=@{APP_REMOTE_WAKE_USE_APP_SCHEDULE='2'}; Error='APP_REMOTE_WAKE_USE_APP_SCHEDULE must'},
    @{Name='command-acks-enabled'; Modem='USE_SIM800'; Defines=@{APP_ENABLE_COMMAND_ACK_REPLIES='true'}; Error=$null},
    @{Name='command-acks-disabled'; Modem='USE_ESP8266'; Defines=@{APP_ENABLE_COMMAND_ACK_REPLIES='false'}; Error=$null},
    @{Name='reject-invalid-command-ack-switch'; Modem='USE_SIM800'; Defines=@{APP_ENABLE_COMMAND_ACK_REPLIES='2'}; Error='APP_ENABLE_COMMAND_ACK_REPLIES must'},
    @{Name='normal-sim'; Modem='USE_SIM800'; Defines=@{}; Error=$null},
    @{Name='valve-test-min-pulse'; Modem='USE_SIM800'; Defines=@{APP_VALVE_OPEN_PULSE_MS='1';APP_VALVE_CLOSE_PULSE_MS='1'}; Error=$null},
    @{Name='valve-test-max-ceiling'; Modem='USE_SIM800'; Defines=@{APP_VALVE_OPEN_PULSE_MS='1000';APP_VALVE_CLOSE_PULSE_MS='1000'}; Error=$null},
    @{Name='reject-valve-negative-pulse'; Modem='USE_SIM800'; Defines=@{APP_VALVE_OPEN_PULSE_MS='-1'}; Error='Valve pulse must'},
    @{Name='reject-valve-large-open'; Modem='USE_SIM800'; Defines=@{APP_VALVE_OPEN_PULSE_MS='1001'}; Error='Valve pulse must'},
    @{Name='reject-valve-large-close'; Modem='USE_SIM800'; Defines=@{APP_VALVE_CLOSE_PULSE_MS='1001'}; Error='Valve pulse must'},
    @{Name='reject-valve-short-interval'; Modem='USE_SIM800'; Defines=@{APP_VALVE_MIN_INTERVAL_MS='999'}; Error='APP_VALVE_MIN_INTERVAL_MS must'},
    @{Name='reject-valve-large-interval'; Modem='USE_SIM800'; Defines=@{APP_VALVE_MIN_INTERVAL_MS='60001'}; Error='APP_VALVE_MIN_INTERVAL_MS must'},
    @{Name='remote-sim'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='2'}; Error=$null},
    @{Name='remote-wifi'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='2'}; Error=$null},
    @{Name='remote-lora'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_UPLINK='2'}; Error=$null},
    @{Name='rtc-wifi'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='1';APP_WIFI_POWER_MODE='1'}; Error=$null},
    @{Name='rtc-lora'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='1';APP_LORA_POWER_MODE='1';APP_UPLINK='2'}; Error=$null},
    @{Name='gateway-wifi'; Modem='USE_ESP8266'; Defines=@{APP_ROLE='2'}; Error=$null},
    @{Name='queued-wifi'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='4';APP_WIFI_POWER_MODE='1'}; Error=$null},
    @{Name='queued-lora'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='4';APP_LORA_POWER_MODE='1';APP_UPLINK='2'}; Error=$null},
    @{Name='wor-lora'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='3';APP_LORA_POWER_MODE='2';APP_UPLINK='2'}; Error=$null},
    @{Name='wor-lora-aux'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='3';APP_LORA_POWER_MODE='2';APP_UPLINK='2';APP_LORA_WOR_WAKE_SOURCE='0'}; Error=$null},
    @{Name='reject-wor-wake-source'; Modem='USE_SIM800'; Defines=@{APP_LORA_WOR_WAKE_SOURCE='99'}; Error='APP_LORA_WOR_WAKE_SOURCE must be AUX or UART_RX'},
    @{Name='gateway-wor'; Modem='USE_ESP8266'; Defines=@{APP_ROLE='2';APP_LORA_GATEWAY_WOR_TX='1'}; Error=$null},
    @{Name='reject-queued-sim'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='4'}; Error='SIM800L periodic POWER_DOWN is unsafe'},
    @{Name='reject-wor-wifi'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='3'}; Error='LORA_WOR requires a LoRa sensor node'},
    @{Name='reject-wor-radio-policy'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='3';APP_UPLINK='2'}; Error='LORA_WOR requires APP_LORA_POWER_MODE'},
    @{Name='reject-wor-gateway'; Modem='USE_ESP8266'; Defines=@{APP_ROLE='2';APP_CONTROLLER_POWER_MODE='3';APP_LORA_POWER_MODE='2'}; Error='gateway must remain NORMAL'},
    @{Name='reject-wor-tx-node'; Modem='USE_SIM800'; Defines=@{APP_LORA_GATEWAY_WOR_TX='1'}; Error='only valid on a LoRa gateway'},
    @{Name='reject-wor-watchdog-margin'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='3';APP_UPLINK='2';APP_LORA_POWER_MODE='2';APP_WATCHDOG_TIMEOUT_US='9000000UL'}; Error='RTC heartbeat must be at least 2 seconds shorter'},
    @{Name='reject-remote-sleeping-wifi'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_WIFI_POWER_MODE='1'}; Error='REMOTE_WAKE requires'},
    @{Name='reject-remote-sleeping-lora'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_LORA_POWER_MODE='1';APP_UPLINK='2'}; Error='REMOTE_WAKE requires'},
    @{Name='reject-remote-sleeping-sim'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_SIM_POWER_MODE='1'}; Error='REMOTE_WAKE requires'},
    @{Name='reject-remote-gateway'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_ROLE='2'}; Error='gateway must remain NORMAL'},
    @{Name='reject-rtc-sim'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='1';APP_SIM_POWER_MODE='1'}; Error='SIM800L periodic POWER_DOWN is unsafe'},
    @{Name='reject-radio-remote-policy'; Modem='USE_ESP8266'; Defines=@{APP_CONTROLLER_POWER_MODE='2';APP_WIFI_POWER_MODE='2'}; Error='Invalid controller or radio power mode'},
    @{Name='reject-controller-policy'; Modem='USE_SIM800'; Defines=@{APP_CONTROLLER_POWER_MODE='99'}; Error='Invalid controller or radio power mode'},
    @{Name='reject-zero-default'; Modem='USE_SIM800'; Defines=@{APP_REMOTE_WAKE_DEFAULT_SECONDS='0UL'}; Error='APP_REMOTE_WAKE_DEFAULT_SECONDS must'},
    @{Name='reject-large-default'; Modem='USE_SIM800'; Defines=@{APP_REMOTE_WAKE_DEFAULT_SECONDS='86401UL'}; Error='APP_REMOTE_WAKE_DEFAULT_SECONDS must'},
    @{Name='reject-fast-poll'; Modem='USE_SIM800'; Defines=@{APP_REMOTE_WAKE_POLL_INTERVAL_MS='9UL'}; Error='APP_REMOTE_WAKE_POLL_INTERVAL_MS must'},
    @{Name='reject-slow-poll'; Modem='USE_SIM800'; Defines=@{APP_REMOTE_WAKE_POLL_INTERVAL_MS='1001UL'}; Error='APP_REMOTE_WAKE_POLL_INTERVAL_MS must'},
    @{Name='network-single-attempt'; Modem='USE_SIM800'; Defines=@{APP_NETWORK_RETRIES_PER_STAGE='1U'}; Error=$null},
    @{Name='network-max-attempts'; Modem='USE_ESP8266'; Defines=@{APP_NETWORK_RETRIES_PER_STAGE='100U'}; Error=$null},
    @{Name='reject-zero-network-attempts'; Modem='USE_SIM800'; Defines=@{APP_NETWORK_RETRIES_PER_STAGE='0U'}; Error='APP_NETWORK_RETRIES_PER_STAGE must'},
    @{Name='reject-large-network-attempts'; Modem='USE_ESP8266'; Defines=@{APP_NETWORK_RETRIES_PER_STAGE='101U'}; Error='APP_NETWORK_RETRIES_PER_STAGE must'}
)
$wakeConfigOriginalPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $wakeConfigCompiler) + ';' + $env:PATH
    $wakeConfigProductionMacros = (& $wakeConfigCompiler '-dM' '-E' '-x' 'c++' '-I' (Join-Path $PSScriptRoot 'fakes') '-DUSE_SIM800' (Join-Path $wakeConfigRoot 'src/config/AppConfig.h') | Out-String)
    if ($LASTEXITCODE -ne 0 -or
        $wakeConfigProductionMacros -notmatch '(?m)^#define APP_WATCHDOG_TIMEOUT_US 30000000UL\s*$' -or
        $wakeConfigProductionMacros -notmatch '(?m)^#define APP_NETWORK_RETRIES_PER_STAGE 10U\s*$' -or
        $wakeConfigProductionMacros -notmatch '(?m)^#define APP_LORA_WOR_WAKE_SOURCE APP_LORA_WOR_WAKE_SOURCE_UART_RX\s*$') {
        throw 'Expected production defaults: 30-second watchdog, 10 retries and UART_RX WOR wake'
    }
    Write-Host 'PASS production defaults: watchdog 30 seconds; network retries 10 + 10; WOR UART_RX wake'
    foreach ($wakeConfigCase in $wakeConfigCases) {
        $wakeConfigDefines = $wakeConfigDefaults.Clone()
        foreach ($wakeConfigName in $wakeConfigCase.Defines.Keys) {
            $wakeConfigDefines[$wakeConfigName] = $wakeConfigCase.Defines[$wakeConfigName]
        }
        $wakeConfigArguments = @('-E','-P','-x','c++','-I', (Join-Path $PSScriptRoot 'fakes'), ('-D' + $wakeConfigCase.Modem))
        foreach ($wakeConfigName in $wakeConfigDefines.Keys) {
            $wakeConfigArguments += '-D' + $wakeConfigName + '=' + $wakeConfigDefines[$wakeConfigName]
        }
        $wakeConfigArguments += @((Join-Path $wakeConfigRoot 'src/config/AppConfig.h'), '-o', 'NUL')
        # An intentional compiler #error is expected for rejected policies.
        $ErrorActionPreference = 'Continue'
        $wakeConfigDiagnostic = (& $wakeConfigCompiler @wakeConfigArguments 2>&1 | Out-String)
        $wakeConfigExitCode = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($null -eq $wakeConfigCase.Error) {
            if ($wakeConfigExitCode -ne 0) { throw "Valid config failed: $($wakeConfigCase.Name): $wakeConfigDiagnostic" }
        } elseif ($wakeConfigExitCode -eq 0 -or -not $wakeConfigDiagnostic.Contains($wakeConfigCase.Error)) {
            throw "Expected guard not observed: $($wakeConfigCase.Name): $wakeConfigDiagnostic"
        }
        Write-Host "PASS config: $($wakeConfigCase.Name)"
    }
    Write-Host "PASS: $($wakeConfigCases.Count) real AppConfig preprocessor policy checks (no configuration edits)"
} finally {
    $env:PATH = $wakeConfigOriginalPath
    $ErrorActionPreference = 'Stop'
}
# Expected compiler rejections are successful test cases, not script failures.
exit 0
