# Schedule-driven remote wake verification

5 October 2026 | Arduino STM32 node | branch feature/2026-10-05-remote-wake-app-schedule

## Scope and implementation

REMOTE_WAKE can now idle between independent SRATE sampling and STRAN Status
deadlines. APP_REMOTE_WAKE_USE_APP_SCHEDULE defaults to true. False retains the
fixed APP_POWER_SLEEP_SECONDS cycle. The other controller profiles are not
changed. This is always-connected light CPU Sleep, not Stop or Standby.

The hardware-independent RemoteWakeCycle policy consumes due/busy indications;
PowerManager reads existing elapsed-millis deadlines without resetting them.
The application reports whether a cooperative sensor cycle remains unfinished,
so it cannot idle halfway through a four-sensor snapshot. Pending transmissions
and replies also prevent idle. Incoming commands retain priority and ordinary
commands do not create an active lease. Explicit WAKE retains its timed ACTIVE
lease, initial fresh work and duplicate/expiry protections.

No server, simulator, schema, pin, ESP32 or CubeIDE source changes are needed.
Existing sensor validity/zero-on-failure behavior, RTC consumption accumulation,
valve controls, optional command ACKs, 30-second IWDG and 10+10 network recovery
are retained. Failed Status attempts follow the existing transmission schedule;
the new policy does not spin awake solely waiting for a successful report.

## Repeatable offline checks

Both the development checkout and final bench copy passed Validate-Release:

- Seven node host suites, including both actual-PowerManager remote policies.
- 158 Python tests: 98 server, 54 across the three sensor simulators, and six
  cross-component release contracts.
- All dashboard JavaScript checks run by Validate-Release.
- 45 real-AppConfig remote/rate/network/valve policy checks, plus eight valve
  configuration checks and 14 valve behavior scenarios.
- A separate final-header power compatibility check: 155 combinations,
  15 accepted and 140 rejected as expected.

The new schedule host profile exercises initial fresh work, independent sample
and transmit deadlines, no legacy interval/command window, unfinished sensor
cycles, queued replies, failed delivery, immediate UART service, live SRATE and
STRAN changes, ordinary commands, WAKE leases/duplicates/expiry and millis
rollover. Fixtures fake hardware only; they compile the actual PowerManager and
CommandHandler with strict C++ warnings. They do not emulate the full modem.

The bench copy intentionally has commissioned valve parameters. Its first
factory-default guard run therefore rejected the test assumption, not firmware
execution. The new optional -UseFactoryConfigurationFixture flag overrides only
the valve guard compiler fixture's pulse/polarity/controller settings, never
the working AppConfig.h. The development release still passes without the flag
and verifies its shipped inhibited-valve defaults. The bench run passes with
the flag, while ARM builds use the actual bench source and explicit profile
selection. No test starts the live server, contacts a broker or flashes hardware.

Example, from the repository root, using installed tool paths:

```powershell
.\Validate-Release.ps1 -Python <python.exe> -Compiler <g++.exe> -NodeJs <node.exe>
# Add -UseFactoryConfigurationFixture only for a commissioned bench copy.
```

## ARM builds and generated documentation

All 16 ARM builds passed: 13 default-policy regression profiles plus three
explicit legacy-remote profiles. Compilation uses STM32 Arduino core 2.12.0, STM32duino RTC 1.9.0 and
BLACKPILL_F401CC with all four sensor drivers enabled. Compile-only valve test
pulses are not manufacturer specifications and are never uploaded.

| Group | Completed profiles |
| --- | --- |
| Default policy | normal-sim; remote-sim/wifi/lora; rtc-wifi/lora; queued-wifi/lora; wor-lora; gateway-wifi/wor; valve-test-sim/wifi |
| Legacy remote (switch=false) | remote-sim; remote-wifi; remote-lora |

Every build's ARM ELF load sections end below reserved EEPROM sector
0x08020000. The largest load endpoint is 0x08016758 (queued-wifi), leaving
39,080 bytes before that sector. The largest reported static RAM use is
26,484 bytes (queued-lora), leaving 39,052 bytes for dynamic use. These are
link/build results, not measured worst-case runtime stack/heap use.

The resumed matrix skipped the profiles that had completed before the user
interrupted the turn. Its evidence is therefore spread across four final-copy
Documentation logs: remote-schedule-arm-build.log,
remote-schedule-arm-resume.log, remote-legacy-arm-build.log and
remote-legacy-arm-resume.log. Together they contain exactly 13 default-policy
and three legacy PASS records. Cached build directories were reused without
deleting sources or private settings. The earlier matrix transcript was backed
up before reuse. Host, compatibility and Doxygen logs are also retained there
under remote-schedule-*.log; generated logs/ELFs are not Git source files.

Doxygen successfully generated in each copy with zero warning-log bytes under the ignored
Node/IoT_Node_Encrypted/Documentation/Doxygen directory. The current remote
guide is included; the older fixed-cycle guide is clearly marked legacy. The
4 October power-mode PDF remains a dated historical artifact and is not
regenerated or presented as current remote timing documentation.

## Final-copy preservation and physical acceptance

Only scoped public files and new macro/documentation/guard entries in AppConfig.h
are synchronized. Original final-folder settings are preserved, including
remote-wake controller, SIM NORMAL, four sensors, node identity and the working
50-ms valve pulses/confirmed polarity. Private AppSecrets.h, AppConfig.cpp and
server node_config.json are checked unchanged. Runtime databases are not
overwritten; concurrent live server database changes are not test failures.
Original public files and FINAL_COPY_INFO.md are backed up under
backups/before_remote_wake_app_schedule_20261005.

Bench acceptance remains required for command latency under SIM/WiFi, four
physical sensors, modem/network loss recovery, physical valve operation and
whole-board current. UART/SysTick, MQTT polling/keepalive and foreground WDT
checkpoints still briefly wake/service the CPU; only application sampling and
Status generation stop between their deadlines. No exclusive-three-interrupt
wake guarantee or unmeasured current reduction is claimed.

Use [the configuration and individual tests](../../Node/IoT_Node_Encrypted/REMOTE_WAKE_APP_SCHEDULE_GUIDE.md).
