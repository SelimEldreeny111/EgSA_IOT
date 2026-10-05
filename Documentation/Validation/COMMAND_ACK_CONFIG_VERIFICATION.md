# Optional command ACK configuration — verification

5 October 2026. Baseline: `7f6a69d784391896d6b840801711704757f2e60c`.
Branch: `feature/2026-10-05-configurable-command-acks`.

## Scope and behavior

`APP_ENABLE_COMMAND_ACK_REPLIES` defaults to true. False suppresses automatic
action-command Telemetry replies, including rejected commands, in the STM32
SIM/WiFi MQTT callback and LoRa sensor-node path. Commands still validate and
execute normally. GOSTM explicitly requests telemetry and still responds;
periodic Status and transport handshakes are unchanged. No server source,
protobuf fields, pins, ESP32 or CubeIDE code changed.

The shared constexpr policy covers all six command IDs. Existing command
request-ID rules, duplicate handling, valve safety checks, WAKE leases and
command-over-sampling priority remain intact. Disabling a reply does not imply
success and does not disable the server's execution validation.

## Regression results

- Development and final-folder full release runners passed: all seven STM32
  host suites, 158 Python tests (98 server, 54 simulator, six contracts),
  all dashboard JavaScript checks, 42 configuration-policy checks and eight
  valve configuration checks.
- Added tests compile the actual MQTT callback for both SIM and WiFi with
  ACKs disabled. Accepted direct actions, legacy VALVE, broadcast WAKE and
  rejected VALVE/WAKE produce no reply. Explicit GOSTM and subsequent periodic
  Status still publish. Existing enabled-reply tests also pass.
- Shared policy decisions are checked for command IDs 1 through 6 in the
  actual command-handler/power-manager host suite. Invalid switch value 2
  is rejected by real AppConfig preprocessing.
- Doxygen was regenerated in both copies with zero warnings, including the
  new configuration guide and API helper documentation.
- All 13 standard STM32 ARM profiles passed with ACKs enabled: normal SIM;
  remote SIM/WiFi/LoRa; RTC WiFi/LoRa; queued WiFi/LoRa; LoRa WOR; two gateways;
  and two compile-only valve fixtures. Maximum flash load end: `0x08015F6C`.
- Three additional ARM builds passed with ACKs disabled: remote SIM, WiFi and
  LoRa. Maximum flash load end: `0x08015594`. Every build includes all four
  sensor drivers and ends below the reserved EEPROM sector at `0x08020000`.

Local logs are preserved in the final folder under
`Documentation/Validation/AckConfigEvidence_20261005`. Standard compiler outputs
remain in `Documentation/FirmwareBuild_20261004`; separate ACK-off outputs are
in `Documentation/FirmwareBuildAckConfig_20261005`. Logs, generated HTML/XML and
compiler outputs are ignored local artifacts, not Git source files.

To repeat the ACK-off ARM checks from the release root with Arduino CLI on PATH:

```powershell
./Node/IoT_Node_Encrypted/tests/remote_wake/run_build_matrix.ps1 `
    -CommandAckReplies false -Profiles @('remote-sim','remote-wifi','remote-lora')
```

## Preservation and limitations

Only public scoped files were copied into the final folder. Its existing bench
AppConfig settings are retained apart from the new enabled-by-default ACK
setting. Replaced public files and metadata are backed up under
`backups/before_configurable_command_acks_20261005`. Private configuration and
runtime databases are hash-checked separately; no production journal is opened.

Hardware was not flashed; no live MQTT broker, server, RS485 port or coil was
used. Callback tests use mocked transports; LoRa runtime behavior still needs
the bench tests in the user guide. Existing third-party compiler warnings are
not new source failures. Compile-only valve pulse fixtures must not be used
as manufacturer commissioning values.

With ACKs disabled, the unchanged server normally reaches Outcome unknown
after its ACK deadline, even if the action executed. Queued rate commands
retain their bounded retry policy. GOSTM responses can still complete their
correlated journal entries. See the
[configuration and bench-test guide](../../Node/IoT_Node_Encrypted/COMMAND_ACK_CONFIG_USER_GUIDE.md).
