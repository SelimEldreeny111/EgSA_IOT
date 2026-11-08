# WIOT STM32 flashing and test manual

Operator edition V1.0

8 November 2026

This manual explains how to configure, compile and flash the Arduino STM32 software, then test each board through the server. It covers direct Wi-Fi nodes, direct SIM800L nodes, LoRa nodes, and a LoRa gateway using Wi-Fi or SIM800L for its MQTT connection.

Use it at the bench in this order. Prepare one labelled build for each board, prove communication in NORMAL mode, add sensors and flash storage, then test the required power policy. Record the result and evidence for each test before changing the next setting.

| Document item | Value |
| --- | --- |
| Source baseline | 9800acc33a5654aff64c4d3ee858292a0c83270f |
| Firmware entry point | Node/IoT_Node_Encrypted/IoT_Node_Encrypted.ino |
| Configuration header | Node/IoT_Node_Encrypted/src/config/AppConfig.h |
| Working release folder | WIOT_Final_PowerModes_20261001 |
| Debug terminal | PA2 TX, PA3 RX, 115200 baud, 8N1 |
| Main programming method | ST-Link with STM32CubeProgrammer over SWD |

The procedures describe expected results. Complete the test record with your measured results, board identities and log files.

## 01 Choose the board profile

The same sketch builds the sensor-node and gateway roles. Configuration decides which code runs. Give each physical board a label and keep its build folder and image with that label.

| Profile | Board and example identity | Communication |
| --- | --- | --- |
| P01 | Wi-Fi sensor node, node 1 | ESP8266 to MQTT |
| P02 | SIM sensor node, node 4 | SIM800L to MQTT |
| P03 | LoRa sensor node, node 2 | LoRa to gateway |
| P04 | Second LoRa sensor node, node 3 | LoRa to the same gateway |
| P05 | Gateway, build identity 100 | LoRa plus ESP8266 MQTT |
| P06 | Gateway alternative, build identity 100 | LoRa plus SIM800L MQTT |

These IDs are a bench example under Company_1 and Region_1. Use your assigned IDs in deployment. P05 and P06 are alternative builds for the gateway in this test setup. Start with one powered gateway.

The gateway uses radio source 0 internally. Its APP_NODE_ID remains a valid nonzero build identity, such as 100, and helps give its MQTT client a unique name. Forwarded measurements retain the leaf node identity. Expect node 2 and node 3 rows on the server, rather than sensor readings from gateway 100.

First-pass sequence

1. Flash and prove P01 or P02 when testing direct communication.
2. Flash and connect P05 or P06 before testing LoRa leaves.
3. Add P03 alone, then P04, then test both leaves together.
4. Enable the intended sensors and archive after basic command and Status exchange passes.
5. Apply the selected low-power recipe and repeat the command and scheduled-work tests.

## 02 Install the tools and dependencies

Use the release-tested versions below when reproducing the working build. Record any different version in the test report.

| Component | Release-tested selection |
| --- | --- |
| Arduino IDE | Arduino IDE with STM32 boards installed |
| STM32 MCU based boards | 2.12.0 |
| STM32duino RTC | 1.9.0 |
| TinyGSM | 0.12.0 |
| PubSubClient | 2.8 |
| AESLib | 2.3.6 |
| SPI and IWatchdog | Supplied by the STM32 core |
| ModbusMaster and nanopb | Supplied inside the project source |

1. Install Arduino IDE and STM32CubeProgrammer, including the ST-Link USB driver. Connect the ST-Link and confirm that Windows detects it.
2. In Arduino IDE Preferences, add the official STM32 board-manager index listed in Section 22.
3. In Boards Manager, select STM32 MCU based boards version 2.12.0 and install it.
4. Use Library Manager to install the listed RTC, TinyGSM, PubSubClient and AESLib versions.
5. Open the sketch and select the board settings in Section 09.

If STM32RTC reports that the core is incompatible, check which library path the compiler selected. Restore the tested core and RTC pair. Multiple Arduino library folders can cause a different copy to take priority. Keep the compatibility check in the library.

The UART buffer options are in build_opt.h beside the sketch. Keep this file and the whole src folder when copying a build profile.

## 03 Prepare a separate build for each board

Work from the final release folder. A profile copy keeps one board's settings separate from another board's settings.

1. Copy the complete Node/IoT_Node_Encrypted folder, including its local configuration files, into a labelled bench folder.
2. Keep the innermost folder name IoT_Node_Encrypted so it matches IoT_Node_Encrypted.ino.
3. Repeat for each board you will flash. For example, use WiFi_Node_1/IoT_Node_Encrypted, SIM_Node_4/IoT_Node_Encrypted, LoRa_Node_2/IoT_Node_Encrypted, LoRa_Node_3/IoT_Node_Encrypted and Gateway_100/IoT_Node_Encrypted.
4. Edit the configuration in the selected copy. Close other copies in Arduino IDE before uploading.
5. After compilation, save the image and configuration record in a folder labelled with that board, role, node ID, modem and power policy.

| File | What to do |
| --- | --- |
| src/config/AppConfig.h | Set role, identity, uplink, sensor addresses, debug and power choices |
| src/config/AppConfig.cpp | Enter the approved Wi-Fi or APN settings, broker and client identity |
| src/config/AppSecrets.h | Provision the approved 16-byte application key |
| src/config/AppConfig.cpp.example | Fresh-clone template for AppConfig.cpp |
| src/config/AppSecrets.example.h | Fresh-clone template for AppSecrets.h |

For a fresh Git clone, copy the two example files to their real filenames before compiling. Keep real credentials and keys in the local files. The node, gateway and server must use the same approved application key. The server key field expects 16 bytes represented by 32 hexadecimal characters.

The current topic template derives company, region and node from the header. Check older private AppConfig.cpp files for hard-coded topics. Every connected MQTT client needs a unique client ID, including the gateway and server.

## 04 Set the common commissioning options

Edit the existing definitions in AppConfig.h. Use one definition for each macro. The snippets in this manual replace the corresponding settings in your profile copy.

For the first communication test, use these choices.

```cpp
#define APP_MQTT_COMPANY "Company_1"
#define APP_MQTT_REGION "Region_1"
#define APP_ENABLE_DEBUG true
#define APP_DEBUG_LITE false
#define APP_DEBUG_RAW_FRAMES false
#define APP_ENABLE_COMMAND_ACK_REPLIES true
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#define APP_WATCHDOG_TIMEOUT_US 30000000UL
#define APP_NETWORK_RETRIES_PER_STAGE 10U
#define APP_WATCHDOG_SELF_TEST_MODE APP_WATCHDOG_SELF_TEST_DISABLED
```

For a communication-only test, set all four sensor flags false and APP_ENABLE_LATCHING_VALVE=false. Enable the sensors later using Section 12. Select APP_ENABLE_SPI_FLASH=true when the flash is fitted. A board without the chip can use false during its first communication test, then be rebuilt for storage testing.

The final folder can contain a previous bench profile, such as node 3 with sensor polling disabled. Read the complete header before building. Recompilation and upload are required after changing a macro.

The compiled startup defaults are a 10-second sampling period and a 15-second transmission period. For the bench tests below, send the specified SRATE and STRAN values after startup. Ordinary restart restores compiled rate defaults.

## 05 Configure direct Wi-Fi and SIM nodes

Use P01 for an ESP8266 node or P02 for a SIM800L node. Both use the sensor-node role and direct MQTT uplink.

| Setting | P01 Wi-Fi example | P02 SIM example |
| --- | --- | --- |
| APP_ROLE | APP_ROLE_SENSOR_NODE | APP_ROLE_SENSOR_NODE |
| APP_UPLINK | APP_UPLINK_MQTT_DIRECT | APP_UPLINK_MQTT_DIRECT |
| APP_NODE_ID | 1 | 4 |
| APP_SENSOR_ID | 1 | 4 |
| Active modem symbol | USE_ESP8266 | USE_SIM800 |
| Controller and all radio power policies | NORMAL | NORMAL |

Define exactly one modem symbol in the transport-selection block. For SIM, select USE_SIM800 and remove the active USE_ESP8266 definition. For Wi-Fi, select USE_ESP8266. Defining both causes a compile error.

P01 preparation

1. Set kWifiSsid and kWifiPassword in the local AppConfig.cpp.
2. Set the broker address and verify a unique kMqttClientId.
3. Connect ESP8266 TXD to STM32 PA12 and ESP8266 RXD to PA11. Connect EN to PB7 and RST to PB8, using the existing board interface. The selected ESP-AT UART runs at 115200 baud.
4. Flash, then check the configured firmware Wi-Fi is attempted first. A distinct saved flash network is the fallback.

P02 preparation

1. Set the SIM operator's APN and any required network username and password.
2. Fit the SIM and antenna and provide the module's required stable supply. Connect SIM TXD to PA12, SIM RXD to PA11 and SIM RST to PB0, using the existing board interface. The selected SIM UART runs at 9600 baud.
3. Flash, then check registration, GPRS and MQTT in that order.
4. Perform the direct-node checks in Section 11 before adding power saving.

The STM32 firmware communicates with the external modem firmware. A successful STM32 upload does not replace the ESP-AT or SIM800 firmware. The project expects the modem UART baud and AT interface already used by the working assembly.

## 06 Configure LoRa node 2 and node 3

P03 and P04 use the same leaf-node recipe with different identities.

```cpp
#define APP_ROLE APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_LORA_TO_GATEWAY
#define APP_NODE_ID 2
#define APP_SENSOR_ID 2
#define APP_LORA_NETWORK_ID 0x4547
#define APP_LORA_GATEWAY_WOR_TX 0
```

For P04, change APP_NODE_ID and APP_SENSOR_ID to 3 in its separate profile copy. Keep the common company and region. Start with controller and radio policies NORMAL.

The header still requires one selected IP modem symbol. Keep a single symbol defined in a LoRa leaf profile. APP_UPLINK_LORA_TO_GATEWAY selects the radio route and excludes direct IP modem initialization. Physically powered unused modules can still draw current.

LoRa leaf wiring

| Module signal | STM32 signal |
| --- | --- |
| TXD | PA12 RX |
| RXD | PA11 TX |
| M0 | PB2 |
| M1 | PB1 |
| AUX | PC13 |
| GND | Common signal ground |

Use matching radio settings in Section 08. The transparent radio address bytes and APP_NODE_ID serve different purposes. The application frame carries the unique leaf ID. Two leaves can use the same radio channel and a common module configuration while retaining different application node IDs.

After flashing, confirm the boot identity on each labelled terminal. Test one leaf at a time, then use Section 11 to test both through the gateway. Keep the radio antenna fitted during transmission.

## 07 Configure the LoRa gateway

Select P05 for a Wi-Fi gateway or P06 for a SIM gateway. It receives the leaf radio frames and forwards their encrypted payloads to MQTT.

```cpp
#define APP_ROLE APP_ROLE_LORA_GATEWAY
#define APP_UPLINK APP_UPLINK_MQTT_DIRECT
#define APP_NODE_ID 100
#define APP_LORA_NETWORK_ID 0x4547
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE APP_COMPONENT_MODE_NORMAL
```

Select USE_ESP8266 for P05 or USE_SIM800 for P06 and provision its network settings. Give the gateway a unique MQTT client ID. Use the same company, region, broker and application key as the leaves.

Set APP_LORA_GATEWAY_WOR_TX=0 for the first NORMAL-only test. Change it to 1 and rebuild the gateway before testing WOR leaves. The gateway remains NORMAL and sends the wake probe before a downlink when WOR TX is enabled.

| Gateway connection | STM32 pins |
| --- | --- |
| LoRa TXD to controller RX | PA10 |
| LoRa RXD to controller TX | PA9 |
| LoRa M0, M1, AUX | PB2, PB1, PC13 |
| IP modem TXD to controller RX | PA12 |
| IP modem RXD to controller TX | PA11 |

The gateway reuses the RS485 UART allocation for LoRa. Its role disables sensor polling and the leaf sample archive. Test SPI history on a sensor node. A gateway FLASH_STATUS request is not a test of a leaf's chip.

The gateway receives both wiot/{company}/{region}/+/cmd and wiot/{company}/{region}/broadcast. Confirm the gateway is MQTT-connected before starting leaf tests.

## 08 Check the LoRa module configuration

The current project profile uses the following settings on every participating radio.

| Item | Current project value |
| --- | --- |
| Frequency and channel byte | 433 MHz and 0x17 |
| UART | 9600 baud, 8N1 |
| Air-rate selection | 2.4 kbit/s |
| Saved configuration bytes | C0 00 00 1A 17 40 |
| Application network | 0x4547 |
| Auto-apply configuration | AS32_AUTO_APPLY_CONFIG=0 by default |

A printed intended configuration is insufficient when auto-apply is disabled. Read the module back and compare it with the project settings.

1. With the module powered correctly, select its configuration mode with M0 HIGH and M1 HIGH. Use a 3.3-V-logic UART adapter with common ground and the configuration UART settings supported by that fitted module.
2. In a hex-capable terminal, send the three raw bytes C1 C1 C1. ASCII characters spelling the hex string are a different transmission.
3. Compare the returned six bytes with the intended configuration. For a confirmed compatible E32/AS32 module, send C0 00 00 1A 17 40 to save that profile, then read it again.
4. Return M0 and M1 to the firmware-controlled connections. Restart the assembly and check communication in NORMAL mode.

The steps above apply to the compatible module used by this project. Use the fitted module's own manual if its configuration command set differs.

E32-TTL-100 UART firmware in this project provides no supported RSSI query. UNSUPPORTED in diagnostics is the expected indication. Assess delivery using valid frames, replies and retry/timeout counters.

## 09 Wire the programmer and select Arduino settings

Power the assembly through its normal supply. Use the target's labelled SWD signals and the probe's actual pin labels.

| ST-Link signal | Target connection |
| --- | --- |
| SWDIO | PA13 / SWDIO |
| SWCLK | PA14 / SWCLK |
| GND | Target GND |
| NRST | Target NRST, required for under-reset recovery |
| VTref when provided | Target 3.3-V reference |

The probe reference connection senses the target logic voltage. Keep modem and board power on their approved supplies. Confirm the pinout of the particular ST-Link adapter before connecting it.

Select these tested project settings in Arduino IDE.

| Arduino option | Selection |
| --- | --- |
| Board package | STM32 MCU based boards 2.12.0 |
| Board series | Generic STM32F4 series |
| Board part number | BlackPill F401CC |
| Upload method | STM32CubeProgrammer (SWD) |
| USB support | None |
| U(S)ART support | Enabled (generic Serial) |
| Optimization | Smallest, default -Os |

These settings reproduce the existing tested STM32 build. Record the actual fitted MCU marking alongside them. A different board variant needs its own pin and build verification.

Use a separate 3.3-V-logic USB-to-TTL adapter for logs. Adapter RX connects to PA2, adapter TX to PA3 when input is needed, and GND to GND. Select that adapter's COM port at 115200 baud, 8N1. The ST-Link programming interface and debug serial terminal are separate connections.

## 10 Compile and flash the selected profile

1. Confirm the label of the connected board and disconnect other programming targets from the probe.
2. Open the intended profile's IoT_Node_Encrypted.ino. Check role, node ID, active modem, uplink and all power policies in that copy.
3. Confirm AppConfig.cpp, AppSecrets.h, build_opt.h and the complete src folder are present.
4. Select the options in Section 09. Press Verify and resolve compilation errors before uploading.
5. Use Sketch > Export Compiled Binary to retain the built image. Store it in the labelled board's image folder with the configuration record.
6. Connect ST-Link over SWD and upload. Wait for the programmer's successful write and verification result.
7. Open the debug adapter's terminal, press RESET and capture the complete boot log.
8. Match the printed role, node ID, company/region, transport, sensor flags and power policy with the intended profile. If they differ, stop and select the correct build.
9. Run T01 in Section 11 and record the image hash and observed identity.

Optional command-line compilation after configuring a profile copy

```powershell
$sketch = 'D:\WIOT_Bench\LoRa_Node_2\IoT_Node_Encrypted'
arduino-cli compile `
  --fqbn 'STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC' `
  --output-dir 'D:\WIOT_Bench\Images\LoRa_Node_2' `
  $sketch
```

The build includes the key and configuration from that profile. Keep its files with the board record. The same .bin filename can be generated for different boards.

The application uses flash base 0x08000000. Its load sections must end below the reserved EEPROM sector at 0x08020000. A general Arduino percentage-of-flash message does not check that reserved boundary. Use the release build checks when changing libraries, options or feature population.

## 11 Start the server and prove communication

Server preparation

1. Run the server from Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard. Use the approved Python environment and install requirements_web.txt when preparing a new PC.
2. On an existing installation, back up its databases before changing server versions and use one ingestion process for those files.
3. Load the approved WIOT environment settings into the server process. First-time accounts require the password variables listed in .env.example. Saving a .env file alone does not load it in this entry point.
4. Start python server_web.py and open http://127.0.0.1:8000. Log in with the provisioned account.
5. As EgSA_Supervisor, configure the broker, a unique server client ID, and the matching key. Connect and wait for readiness with SUBACK confirmation.
6. Select Company_1 and Region_1, or the deployment's assigned scope. Use the individual node ID when sending a direct command.

| Test | Action | Pass evidence |
| --- | --- | --- |
| T01 Boot identity | Reset the newly flashed board and inspect its log | Correct role, identity and policy, with a 30000 ms nominal WDT |
| T02 Direct node | For P01 or P02, wait for Status, then send GOSTM | New Status on /status and a matching node/request reply on /data |
| T03 LoRa leaf | Start a connected gateway, then node 2 alone and send GOSTM to 2 | Gateway uplink source 2 and server reply scoped to node 2 |
| T04 Second leaf | Start node 3 and send GOSTM to 3, then repeat for 2 | Separate correct replies for both targets |

For the shared-channel test, start node 3 after node 2's initial report. Use SRATE/STRAN=60/120 seconds on node 2 and 90/180 on node 3, then observe at least ten reports from each. Record timeouts and retries. Persistent losses need RF, timing and supply investigation.

Send a regional GOSTM broadcast as a separate test and verify a reply from each leaf. A non-target leaf can log an overheard command or fragment without being the target. Use the addressed board and the server request ID to judge the result.

## 12 Test the four RS485 sensors

Use the multi-sensor simulator first. Connect its USB-to-RS485 adapter to the sensor node's RS485 bus, with compatible polarity and signal reference. One master controls a physical RS485 bus. For two sensor nodes, use separate buses or test them one at a time.

The sensor node uses PA9 TX to the transceiver DI, PA10 RX from RO and PA8 for the tied direction controls. Connect the adapter to the transceiver bus terminals, rather than directly to the MCU UART pins. Match RS485 positive and negative polarity using the adapter and board labels. Use 9600 baud, 8 data bits, no parity and 1 stop bit.

1. Open the multi-sensor EXE under SENSORS/Multi Sensor RS485 Simulator/dist/20261025, or run multi_sensor_simulator.py with its requirements installed.
2. Load stm32_four_sensor_config.json. The demonstration default_config.json uses different sensor types and addresses.
3. Select the actual adapter COM port and 9600 baud, no parity, one stop bit. Close other programs that own that port.
4. In the node profile, enable only the sensor being tested and set its matching APP_*_SENSOR_MODBUS_ADDRESS. Compile and flash again.
5. Compare the simulator, FULL serial log and server values. Repeat for each type, then enable all four together.

| Sensor and address | Fixture values | Settings to match |
| --- | --- | --- |
| TUF, 1 | Flow 12.50 m3/h, velocity 1.25 m/s | APP_ENABLE_TUF_SENSOR and APP_TUF_SENSOR_MODBUS_ADDRESS |
| Supmea, 2 | Flow 38.00 m3/h, velocity 4.00 m/s | APP_ENABLE_SUPMEA_SENSOR and APP_SUPMEA_SENSOR_MODBUS_ADDRESS |
| HNDA, 3 | Temperature 23.5 C, moisture 35.6 percent | APP_ENABLE_HNDA_SENSOR and APP_HNDA_SENSOR_MODBUS_ADDRESS |
| Sondas, 4 | Temperature 24.0 C, moisture 42.0 percent, EC 850 | APP_ENABLE_SONDAS_SENSOR and APP_SONDAS_SENSOR_MODBUS_ADDRESS |

T05 passes when each enabled group has the expected decoded value and valid indication, and disabled sensors generate no requests. TUF is the primary flow record when both meters are enabled. Supmea then appears in the secondary flow record. The soil probes have separate fields.

The Sondas simulator implements the current WIOT compatibility register map. Check the purchased physical probe's communication type, registers and EC units before accepting that hardware.

## 13 Test failed sensors and command timing

T06 Unavailable readings

1. Establish valid readings with all intended sensors enabled. Keep NORMAL mode for this test.
2. Mute one simulator device. Allow the node to finish its next acquisition, including timeouts and any archive write.
3. Check the next eligible Status. That sensor group should contain zeros and invalid quality. Other valid groups should remain usable.
4. Mute all enabled devices and repeat. Reports must continue after completed cycles, with failed fields marked invalid.
5. In a separate build, disable all four polling flags. A fresh sample should have sensor mask zero while command replies and periodic Status remain available.
6. Restore the devices and confirm validity recovers.

T07 Command and rate behavior

1. Send GOSTM to the individual node. Match the server request ID to the node reply.
2. Send SRATE=30 and STRAN=60. Confirm acknowledgements, then observe separate read and report times.
3. Change to SRATE=60 and STRAN=30. The faster reports may legitimately repeat the last completed sample.
4. Send a command during a sensor wait and during a flash-history transfer. Record reception-to-reply time.
5. Try an invalid rate of 5 seconds on a bench target. The node's supported range is 10 to 86400 seconds.

Command processing has cooperative priority. An in-progress driver transaction or LoRa transfer can add latency. Measure the result on the actual link. Distinguish a server receipt timestamp from the stored sample's acquisition timestamp.

## 14 Synchronize RTC and compare water totals

T08 Supmea day month and year comparison

1. Use NORMAL mode and one Supmea device initially. Send STIME using the server's current UTC time. Confirm RTC trust in the node log or reply.
2. Set the simulator Supmea flow to 36.0 m3/h, volumetric unit code 3, auto totalizers enabled and time multiplier 1.
3. In the simulator's SUPMEA RTC test tab, choose the same calendar as the node, normally Africa/Cairo. Start or reset the comparison reference.
4. Allow the node to acquire its first trusted cumulative baseline. Record node and simulator starting day/month/year values.
5. Keep the flow fixed and compare changes after a measured interval. At 36 m3/h, 60 seconds represents 0.600 m3. Compare deltas over the same start and end times, allowing for polling and display resolution.
6. Export the simulator reference and capture the node results. Repeat a longer interval and a controlled calendar boundary test separately.

The first trusted baseline can correctly report zero consumption. The node derives Supmea periods from changes in cumulative forward volume. The simulator reference independently integrates flow and displays its own periods. These reference values do not add day/month/year registers to the RS485 reply.

TUF reads its own meter-native day/month/year values. Test those values against the TUF simulator fields or the physical meter display. Use fixed TUF period values if checking register decoding without totalizer evolution.

Re-synchronize time after ordinary startup when RTC trust is absent. A seeded date such as 2024-01-01 is insufficient for accepting calendar calculations, WOR scheduling or retention tests.

## 15 Test the external flash and history commands

T09 Integrated storage commissioning

1. Use a sensor-node profile with APP_ENABLE_SPI_FLASH=true and the fitted S25FL064L. Connect PA4 CS, PA5 SCK, PA6 MISO and PA7 MOSI at 3.3-V logic with common ground.
2. Send STIME, then direct FLASH_STATUS. Expect JEDEC 01 60 17 and physical capacity 8388608 bytes. Blank media can report Unformatted.
3. If initializing a disposable or approved-to-clear log, send CLEAR_FLASH to the individual node. Confirm acceptance and wait for Ready, with reclamation complete, before judging clear completion.
4. Allow complete sensor cycles. Query FLASH_STATUS again and confirm committed record count and sequence advance.
5. Send FLASH_LAST. Compare the original acquisition time and values with the last committed sample.

T10 Download and retention

1. Send FLASH_TODAY with a fresh request. Wait for the explicit terminal result and compare the frozen record total with the server archive rows.
2. Check the history/archive view and CSV. Downloaded records have their original timestamps and do not become new live acquisitions.
3. Repeat with new acquisitions during the download, then with FLASH_CANCEL during a separate run.
4. Record the retention start and run the real 24-hour test. The generation expires after 86400 elapsed seconds. Midnight alone does not clear it.
5. Reboot during an idle interval and confirm the retained committed records and original retention start recover.

FLASH_TODAY selects the currently retained portion of the node's calendar day. Its result can contain fewer than a full day's records after an elapsed-time rollover.

The server stores each history record before sending internal HISTORY_ACK. A radio fragment ACK or broker receipt does not establish that database persistence completed. CLEAR_FLASH discards the node's retained sample batch, so use it deliberately.

## 16 Select and test the power policy

First prove the corresponding NORMAL profile. Then edit the existing power macros in that board's copy, recompile and flash.

| Controller policy | Selected radio policy | Intended wake behavior |
| --- | --- | --- |
| NORMAL | NORMAL | Continuous foreground work |
| REMOTE_WAKE | NORMAL | CPU idle between due work, while the modem or radio remains reachable |
| LORA_WOR | LoRa WAKE_ON_RADIO | STM32 Stop, UART RX radio wake and RTC work deadlines |
| POWER_DOWN | ESP or LoRa POWER_DOWN | RTC Standby cycle, with startup after wake |
| QUEUED | ESP or LoRa POWER_DOWN | Standby cycle plus server commands at the next connected window |

Keep inactive component policies NORMAL unless a supported recipe explicitly requires otherwise. The compiler checks the selected pairing. A gateway uses NORMAL. Direct SIM800L Standby/POWER_DOWN and queued Standby are blocked on the present wiring. Use SIM NORMAL with controller REMOTE_WAKE for the reachable-idle test.

T11 REMOTE_WAKE test for Wi-Fi, SIM or normal LoRa

1. Set APP_CONTROLLER_POWER_MODE=APP_COMPONENT_MODE_REMOTE_WAKE and keep the active radio NORMAL. Set APP_REMOTE_WAKE_USE_APP_SCHEDULE=true.
2. After flashing and confirming connectivity, send SRATE=60 and STRAN=120. Observe that unrelated fixed sleep values do not start extra acquisitions.
3. Send GOSTM during idle and verify its reply. Send WAKE=15 separately and verify the active lease ends before idle resumes.
4. Record current at a stated measurement point, command latency, sample times and Status times.

CPU Sleep keeps interrupt and service activity. A WAKE argument requests active seconds. It is separate from the idle interval. The 30-second IWDG remains active.

## 17 Test LoRa WOR and independent deadlines

T12 uses a WOR leaf and an updated NORMAL gateway.

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_LORA_WOR
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_WAKE_ON_RADIO
#define APP_LORA_WOR_WAKE_SOURCE APP_LORA_WOR_WAKE_SOURCE_UART_RX
#define APP_LORA_WOR_USE_APP_SCHEDULE true
#define APP_LORA_WOR_WATCHDOG_WAKE_SECONDS 15UL
```

1. Rebuild the gateway with APP_LORA_GATEWAY_WOR_TX=1. Keep its controller and radios NORMAL.
2. Flash the leaf with the recipe above. AUX remains connected to PC13 for readiness. LoRa TXD to PA12 supplies the UART RX wake edge.
3. While reachable, send STIME. For storage testing, also confirm FLASH_STATUS is Ready. Untrusted RTC keeps the node awake.
4. Send SRATE=100 and STRAN=300. APP_POWER_SLEEP_SECONDS may remain 20 in this bench profile. With application scheduling true, it does not set WOR acquisition or report deadlines.
5. Allow work and the receive window to finish. Look for wake_source=UART_RX and WOR Stop requested, with M0=0 and M1=1.
6. Observe the RTC maintenance wakes, up to 15 seconds apart. They service IWDG and return to Stop when no application work is due.
7. Confirm acquisitions follow SRATE and routine Status follows STRAN. Then swap to SRATE=300 and STRAN=100 and verify a send-only wake does not force a sensor read.
8. During a quiet Stop interval, send GOSTM or FLASH_STATUS. Confirm wake, valid decoded command, server reply and return to low idle current.
9. Repeat with both leaf nodes and record delivery and retry behavior separately for each ID.

Measure current for the stated assembly and average over complete cycles. The earlier approximately 9 mA bench observation is a reference observation, rather than a required value for every hardware population. The RTC schedules normal wakeups. IWDG expiry causes a reset.

APP_LORA_WOR_USE_APP_SCHEDULE=false selects the older combined cycle based on APP_POWER_SLEEP_SECONDS. Use that setting only when testing that legacy behavior.

## 18 Test Standby and queued delivery

T13 Periodic Standby

1. Use a direct ESP8266 or LoRa sensor node. Set controller POWER_DOWN and the selected radio POWER_DOWN. Use APP_POWER_SLEEP_SECONDS=60 for a short bench cycle.
2. Flash and establish communication and valid time. Wait for the initial sample/report and the configured command window.
3. Observe entry into Standby and wake after the RTC interval. Startup and network reconnection add time to the full cycle.
4. Confirm a new report after startup. Inspect reset counters and cause so planned Standby is distinguished from power loss or a WDT event.

T14 Queued delivery

1. Set controller QUEUED with the selected ESP8266 or LoRa radio POWER_DOWN. Keep a suitable APP_QUEUED_COMMAND_WINDOW_MS and trusted RTC.
2. While the node is sleeping, submit a harmless GOSTM or rate command using next-wake delivery. Set the server TTL longer than the sleep, startup and reconnect interval.
3. At the next Status/connected window, match the queued dispatch and the node reply by request ID.
4. Confirm command expiry in a separate test where the node stays unavailable past its TTL.

A fully sleeping Standby node receives queued work at a later connected window. Use REMOTE_WAKE or LoRa WOR when immediate remote reception is required by the chosen hardware setup.

Pending flash writes, recovery, history transfers or active leases can defer sleep. If the node stays awake, inspect those conditions before treating current draw as a power-mode failure.

## 19 Test watchdog counters and network recovery

T15 Reset classification and counters

1. Record power_reset_count and wdt_reset_count from a fresh GOSTM reply.
2. Press RESET or perform a software reset. Verify neither cause-specific counter increments solely for that action.
3. Remove and reapply the supply. Verify the power-on/brownout count increments.
4. For a controlled WDT test, disconnect the valve load and use a separate profile with APP_WATCHDOG_SELF_TEST_MODE=APP_WATCHDOG_SELF_TEST_MAIN_LOOP. Flash it and capture one injected stall and IWDG reset.
5. Confirm the boot cause/stage and WDT increment. Reflash the normal profile with self-test DISABLED immediately. The self-test image can repeat its stall after each boot.
6. If clearing is intended, send CLEAR_POWER_RESETS or CLEAR_WDT_RESETS directly with data 0. Confirm the selected count becomes zero and the other is preserved.

T16 Network recovery for P01, P02, P05 or P06

1. Start connected, then make the actual selected Wi-Fi network or SIM service unavailable. Account for the saved Wi-Fi fallback.
2. Observe returned failed network attempts. At ten failures, expect the active modem reset. At another ten, expect modem reset and controller reset.
3. Restore service before a threshold in a separate run and confirm the failure stages clear.
4. Test a broker-only outage separately. It exercises MQTT reconnect and does not count as a failed Wi-Fi/GSM network join.

The SIM reset uses PB0, and ESP reset uses PB8 with EN on PB7. Verify the physical reset signal. A modem call that stays blocked beyond the nominal 30-second watchdog window can cause global IWDG reset before the retry thresholds are reached. Ten retries are a count of completed failures, rather than a duration in seconds.

## 20 Test voltage valve and launch debug

T17 Battery reading

1. Measure battery voltage with a meter and request GOSTM. Compare with the reported value using the configured divider and calibration.
2. Repeat at several suitable input voltages. Monitor the controller's 3.3-V rail during modem and LoRa transmission if resets occur.
3. Record the measurement point, meter range, input voltage and powered modules for each current test.

T18 Commissioned valve on a direct node

1. Confirm the approved TB6612FNG wiring, common ground, coil supply, opening polarity and pulse durations. The current bench header carries 50 ms values and a confirmed polarity flag, which must agree with the fitted valve's commissioning record.
2. Use a direct-IP node where the valve pins are available. Set APP_ENABLE_LATCHING_VALVE=true only for this commissioned test. PB9/PB15 control direction, PC13 controls STBY and PWMA is held HIGH by hardware.
3. Send VALVE=1 and VALVE=0 as separate commands. Verify physical action, the correlated result and commanded-state telemetry. The bridge turns off after the pulse.
4. A LoRa profile reserves PC13 for AUX and inhibits this valve output. Use the actual pin allocation when selecting a test board.

T19 Launch debug

| Choice | APP_ENABLE_DEBUG | APP_DEBUG_LITE | Result |
| --- | --- | --- | --- |
| FULL | true | false | Detailed bench diagnostics |
| LITE | true | true | Boot, command, report and critical events |
| OFF | false | either | Diagnostic UART output disabled |

Rebuild once for each required debug choice. Confirm command replies, sampling and reports still work. APP_DEBUG_RAW_FRAMES affects dumps in FULL. APP_ENABLE_COMMAND_ACK_REPLIES separately controls automatic action replies. Keep it true during acceptance so command results can be correlated.

T20 Soak test runs the selected final profile for at least 48 hours, including two retention rollovers when storage is enabled. Record resets, missing reports, command latency, history completeness and recovery from a controlled link outage.

## 21 Troubleshooting and test record

| Symptom | First check | Next action |
| --- | --- | --- |
| AppConfig.cpp or AppSecrets.h missing | The local files exist under src/config | Create them from examples and provision approved values |
| STM32RTC incompatibility error | Selected core, RTC version and compiler library path | Restore the tested 2.12.0 and 1.9.0 pair |
| No debug text | Adapter RX to PA2, baud 115200, FULL/LITE enabled | Open the terminal first and press RESET |
| No SWD connection | Target power, common ground, PA13, PA14, NRST | Use under-reset recovery in Section 22 |
| Topic and payload ID mismatch | Profile node ID and private topic definitions | Rebuild the correct identity and verify the boot log |
| Status works but GOSTM does not | Company/region/target, gateway subscriptions, ACK/request logs | Trace server TX, gateway forwarding, addressed leaf and reply |
| LoRa awake-only command response | Gateway WOR TX and leaf time trust | Follow Section 17, including UART RX wake and matching radio settings |
| Sensor zeros | Enabled flag, address, 9600 8N1 and simulator fixture | Restore replies and wait for a completed acquisition |
| Supmea periods zero | Trusted RTC, baseline and advancing forward total | Follow the fixed-flow delta comparison in Section 14 |
| Flash replies missing | Updated gateway, correct leaf target and matching server/schema | Trace FLASH_STATUS or history by request ID |
| Standby does not accept an immediate command | Selected controller and radio policy | Test next-wake delivery or choose the reachable profile |
| Power count does not change after RESET | Actual reset method | Perform the controlled supply-cycle test |

### Test record

Copy this page into the bench report for each test. Fill in the evidence and measured result before moving to the next profile.

| Field | Record |
| --- | --- |
| Test ID and result | T01 through T20, Pass / Fail / Not run |
| Target | Board label, MCU marking, node ID, company and region |
| Software | Source commit, image path, SHA-256 and library versions |
| Profile | Role, modem, uplink, sensor flags/addresses and power policy |
| Setup | Wiring, supplies, simulator fixture and COM ports |
| Evidence | Boot log, server request ID/log, sample times and screenshots |
| Measurements | Voltage/current point, range, duration and observed values |
| Closure | Defect reference, retest result, tester and date |

Result   Pass / Fail / Not run

Observed behavior and measurements

________________________________________________________________________

________________________________________________________________________

Evidence file or screenshot reference

________________________________________________________________________

Tester and date

________________________________________________________________________

Release the board with self-test disabled, the intended debug choice, verified identity, restored normal sensor behavior, and the approved valve settings. Keep the matching image and configuration record available for recovery.

## 22 Recovery commands and reference files

Program an exported image with STM32CubeProgrammer when Arduino upload is unavailable.

1. Select ST-LINK and SWD, choose the connected probe and connect to the labelled target. Check that the detected device and memory match the board.
2. Open the image for that exact profile. A .bin uses start address 0x08000000. ELF and HEX contain their own addresses.
3. Enable verification and program the image. Keep the existing internal EEPROM sector when preserving configuration and counters. Avoid a full-chip erase in the normal update path.
4. Reset and run, then repeat T01 and the transport test. Ordinary MCU programming does not initialize the external S25FL064L archive.

For a sleeping or repeatedly resetting target, connect NRST from ST-Link, choose Connect Under Reset and Hardware reset, lower the SWD frequency if needed, and retry the same verified image. Keep BOOT0 in the normal application position after programming. Use the exact supported options in your installed programmer.

Optional read-only SPI check uses Test_SPI_Flash/Test_SPI_Flash.ino. Leave TEST_ALLOW_ERASE=false, flash it temporarily, and use r to read JEDEC/status. Restore the node application afterwards. The optional t test with TEST_ALLOW_ERASE=true erases the last 4 KB sector, which the production journal uses. Run it only when that retained data may be discarded.

| Reference | Location or source |
| --- | --- |
| Board package installation | https://stm32duino.github.io/dev/Getting-Started/ |
| Board manager index | https://github.com/stm32duino/BoardManagerFiles/raw/main/package_stmicroelectronics_index.json |
| STM32CubeProgrammer instructions | https://www.st.com/resource/en/user_manual/dm00403500-stm32cubeprogrammer-stmicroelectronics.pdf |
| Programmer command reference | https://dev.st.com/stm32cube-docs/prog/2.23.0/en/docs/markup/CubeProg_Command_Lines.html |
| Working profile and two-node checks | Documentation/Validation/WIOT_SYSTEM_REVIEW_20261104.md |
| Radio wiring and configuration | Node/IoT_Node_Encrypted/RADIO_AND_VOLTAGE_GUIDE.md |
| WOR deadlines | Node/IoT_Node_Encrypted/LORA_WOR_APP_SCHEDULE_GUIDE.md |
| Storage acceptance | Node/IoT_Node_Encrypted/SPI_FLASH_TEST_PLAN.md |
| Reset counters and simulator comparison | Node/IoT_Node_Encrypted/RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md |
| Complete software design | Documentation/NodeSoftwareDesign/WIOT_STM32_Node_Software_Design_V1.2.docx |

Repository paths in this manual are relative to WIOT_Final_PowerModes_20261001. Keep this manual with the image and test records for the deployed boards.
