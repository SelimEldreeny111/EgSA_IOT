# WIOT handover verification

9 November 2026 · STM32 Arduino release

## Software results

The release validator completed ten node host suites, eight dashboard scripts and 199 Python tests. The normal release matrix compiled fourteen firmware profiles. Four additional checks covered NORMAL Wi-Fi, Wi-Fi without the external archive, a SIM gateway with WOR TX, and the active final-folder node 3 build. All eighteen images stayed below the reserved EEPROM sector.

| Python group | Passed |
| --- | ---: |
| Multi-sensor simulator | 34 |
| TUF simulator | 20 |
| Supmea simulator | 11 |
| Server | 124 |
| Cross-component contract | 10 |

The host suites cover valve guards and pulse cutoff, MQTT priority, modem recovery, reset classification, unavailable sensors, RTC/Supmea, remote idle, LoRa WOR, flash recovery and debug modes. Dashboard checks cover sensor validity, wake and valve results, escaping, command timelines, reset controls, regions and history.

The build uses the installed STM32 Arduino 2.12.0 BLACKPILL_F401CC profile. The flash load end is calculated from the loadable ARM ELF sections.

| Build | Flash load end | Result |
| --- | --- | --- |
| normal-sim | 0x080164F4 | Pass |
| remote-sim | 0x08016844 | Pass |
| remote-wifi | 0x080159B8 | Pass |
| remote-lora | 0x08014D64 | Pass |
| rtc-wifi | 0x0801603C | Pass |
| rtc-lora | 0x08015424 | Pass |
| queued-wifi | 0x080160CC | Pass |
| queued-lora | 0x080154B8 | Pass |
| wor-lora | 0x08017288 | Pass |
| wor-lora-aux | 0x08017154 | Pass |
| gateway-wifi | 0x0800BDB8 | Pass |
| gateway-wor | 0x0800BE28 | Pass |
| valve-test-sim | 0x080164FC | Pass |
| valve-test-wifi | 0x08015670 | Pass |
| normal-wifi | 0x08015668 | Pass |
| flash-disabled-wifi | 0x08012F24 | Pass |
| gateway-sim-wor | 0x0800CCB8 | Pass |
| final-node-3 | 0x08018C14 | Pass |

The active node 3 build used 100,864 program bytes and 34,572 bytes of static RAM. Its load end at 0x08018C14 leaves 29,676 bytes before the reserved EEPROM sector at 0x08020000.

A normalized comparison of 144 tracked implementation files in the release checkout and final working folder found one difference, the local AppConfig.h board profile. Private configuration files are outside this comparison.

## Reproduce the checks

From the repository root in PowerShell with the project toolchain and dependencies installed:

```powershell
./Validate-Release.ps1 -Python "C:/Python314/python.exe" -UseFactoryConfigurationFixture -BuildFirmware
```

For the two extra Wi-Fi profiles, run the existing remote-wake build matrix with Profiles set to normal-wifi and flash-disabled-wifi. For the SIM gateway, use profile P06 with gateway identity 100, NORMAL power policies and APP_LORA_GATEWAY_WOR_TX=1. For the final node 3, compile its existing working profile. Verify the load end of each ELF against the EEPROM boundary.

## Handover verification

The editable Word report was refreshed in Word, exported to a QA PDF and reviewed as eight rendered pages. The handover index links the current manuals, flowcharts and source entry points. Edge played the video over a loopback preview and loaded 25 caption cues and eight chapter cues. Desktop and mobile views fit their viewports. FFmpeg decoded the complete 1280 × 720 video and narration. The video runs 4 minutes 30 seconds.

## Physical acceptance

Use tests T01–T20 in the flashing manual on the intended boards. Record RS485 values and timeout recovery, MQTT and LoRa delivery, current, reset causes, RTC/flash retention, physical valve movement where fitted, and the 48-hour soak. The automated results cover software behavior and compile viability. The bench record captures deployment performance.
