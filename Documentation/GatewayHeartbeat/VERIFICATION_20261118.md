# Gateway heartbeat verification

18 November 2026 • Arduino STM32 release

## Completed software checks

| Check | Result |
|---|---|
| Server Python suite | 130 tests passed |
| Cross-component release audit | 10 tests passed |
| Production gateway-loop host harness | Enabled and disabled heartbeat profiles passed |
| Gateway dashboard JavaScript harness | States, quiet nodes, safe text and region switching passed |
| Existing regional UI and safe-HTML harnesses | Passed |
| Existing MQTT host suite | SIM/Wi-Fi priority, gateway forwarding, recovery and real PubSubClient paths passed |
| Existing flash host suite | Recovery, retention, full capacity, CRC, queue, I/O and 13 write/erase power-cut transitions passed |
| Flash archive/driver and radio transport host tests | Capture, download, retries, cancellation, retention, manual clear and large-frame reassembly passed |
| Protobuf consistency and generated descriptors | Arduino and both server schema sources passed |
| Whitespace validation | git diff --check passed |

## STM32 Arduino compilation

Board is `STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC`, core 2.12.0. Every profile compiles the four sensor drivers. Flash-load checks verify separation from the EEPROM emulation sector at `0x08020000`.

| Profile | Sketch bytes reported by Arduino | Static RAM bytes | Flash-load end |
|---|---|---|---|
| Wi-Fi gateway | 55,836 | 30,604 | `0x0800DC2C` |
| Wi-Fi gateway with WOR downlinks | 55,948 | 30,604 | `0x0800DC9C` |
| SIM800 gateway | 59,540 | 30,604 | `0x0800EAA4` |
| Normal Wi-Fi sensor node | 87,164 | 25,988 | `0x08015690` |
| WOR LoRa sensor node | 94,332 | 34,644 | `0x08017290` |

Build and test scratch files were redirected to `D:/WorkSpace/EgSA/R&D_WS/IOT/IOT/WIOT/tmp/gateway_heartbeat_20261118` after the initial attempt exhausted C-drive space. The listed final builds and server checks completed using the D-drive scratch directory.

## Working-copy integration

Updated source, generated schemas, tests and documentation are copied to `WIOT_Final_PowerModes_20261001`. The final folder's existing AppConfig.h settings are retained while the three new heartbeat configuration options are inserted. Other delivered files are verified against the reviewed Git worktree.

## Hardware acceptance

Physical heartbeat transmission, modem-network reconnection and dashboard observation remain bench acceptance tasks. Follow `WIOT_Gateway_Heartbeat_Design_and_Test.md`, beginning with all sensor nodes powered off. Existing physical SPI identification, erase and page-program/readback results supplied by the operator support the flash interface explanation.
