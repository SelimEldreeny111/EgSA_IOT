param([string]$CompilerPath='g++',
    [string]$PubSubClientSource=(Join-Path $env:USERPROFILE 'OneDrive/Documents/Arduino/libraries/PubSubClient/src'))
$ErrorActionPreference='Stop'
$mqttTestNode=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$mqttTestBuild=Join-Path ([IO.Path]::GetTempPath()) ('wiot-mqtt-priority-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $mqttTestBuild | Out-Null
$mqttTestCompiler=(Get-Command $CompilerPath).Source
$mqttTestOldPath=$env:PATH
try {
    $env:PATH=(Split-Path -Parent $mqttTestCompiler)+';'+$env:PATH
    $mqttTestFakes=Join-Path $PSScriptRoot 'fakes'
    $mqttTestExe=Join-Path $mqttTestBuild 'mqtt_priority_test.exe'
    & $mqttTestCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        '-I' $mqttTestFakes '-include' (Join-Path $mqttTestFakes 'TestAppConfig.h') `
        (Join-Path $mqttTestNode 'src/comm/MQTT.cpp') `
        (Join-Path $PSScriptRoot 'mqtt_priority_test.cpp') '-o' $mqttTestExe
    if($LASTEXITCODE -ne 0) { throw 'MQTT host build failed' }
    foreach($scenario in @('success','zero_write','partial_write','command_priority',
        'receive_during_pending_send','ack_retry','queue_backpressure','foreign_node','subscribe_failure','idle_empty',
        'modem_recovery','controller_recovery','gprs_recovery','broker_only','legacy_valve_reply')) {
        & $mqttTestExe $scenario
        if($LASTEXITCODE -ne 0) { throw "MQTT test failed: $scenario" }
    }
    $mqttWifiExe=Join-Path $mqttTestBuild 'mqtt_priority_wifi_test.exe'
    & $mqttTestCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' '-DTEST_ESP8266' `
        '-I' $mqttTestFakes '-include' (Join-Path $mqttTestFakes 'TestAppConfig.h') `
        (Join-Path $mqttTestNode 'src/comm/MQTT.cpp') `
        (Join-Path $PSScriptRoot 'mqtt_priority_test.cpp') '-o' $mqttWifiExe
    if($LASTEXITCODE -ne 0) { throw 'ESP8266 MQTT host build failed' }
    foreach($scenario in @('command_priority','ack_retry','modem_recovery','controller_recovery')) {
        & $mqttWifiExe $scenario
        if($LASTEXITCODE -ne 0) { throw "ESP8266 MQTT test failed: $scenario" }
    }
    $modbusExe=Join-Path $mqttTestBuild 'modbus_wait_test.exe'
    & $mqttTestCompiler '-std=c++14' '-Wall' '-Wextra' '-I' $mqttTestFakes `
        (Join-Path $mqttTestNode 'src/third_party/ModbusMaster/ModbusMaster.cpp') `
        (Join-Path $PSScriptRoot 'modbus_command_wait_test.cpp') '-o' $modbusExe
    if($LASTEXITCODE -ne 0) { throw 'Actual Modbus host build failed' }
    foreach($scenario in @('response_after_command','offline','bad_crc')) {
        & $modbusExe $scenario
        if($LASTEXITCODE -ne 0) { throw "Modbus command wait failed: $scenario" }
    }
    if(!(Test-Path -LiteralPath (Join-Path $PubSubClientSource 'PubSubClient.cpp'))) {
        throw 'Provide -PubSubClientSource to run the actual installed library test'
    }
    $realPubsubExe=Join-Path $mqttTestBuild 'real_pubsub_test.exe'
    & $mqttTestCompiler '-std=c++14' '-Wall' '-Wextra' `
        '-I' $PubSubClientSource '-I' $mqttTestFakes `
        '-include' (Join-Path $mqttTestFakes 'TestAppConfig.h') `
        (Join-Path $mqttTestNode 'src/comm/MQTT.cpp') `
        (Join-Path $PubSubClientSource 'PubSubClient.cpp') `
        (Join-Path $PSScriptRoot 'real_pubsub_test.cpp') '-o' $realPubsubExe
    if($LASTEXITCODE -ne 0) { throw 'Actual PubSubClient host build failed' }
    & $realPubsubExe
    if($LASTEXITCODE -ne 0) { throw 'Actual PubSubClient protocol test failed' }
} finally { $env:PATH=$mqttTestOldPath }
