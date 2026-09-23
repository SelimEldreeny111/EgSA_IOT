# Port validation record

Validation performed with STM32CubeIDE 2.2.0 and GNU Tools for STM32 14.3.rel1 targeting `STM32F401RCTx`:

- CubeIDE project metadata (`.project` and `.cproject`) parsed successfully.
- CubeIDE-generated makefiles compiled and linked both `SensorNode` and `LoRaGateway` with no application warnings.
- `SensorNode`: text 38,844 B, data 172 B, BSS 9,300 B.
- `LoRaGateway`: text 25,188 B, data 92 B, BSS 10,964 B.
- AES-128-CBC implementation passed the NIST CBC vector in `Tests/aes_cbc_vector_test.cpp`.
- Ported `sensor.proto` is byte-identical to the current Arduino project schema. SHA-256: `1173A6FBD1BE23606CDC690904D6B043E756DFB34E48F21BDFA1EFFEB3B24C14`.
- No Arduino core, TinyGSM, PubSubClient, HardwareSerial, or SoftwareSerial include remains in the native firmware.

Flashable BIN checksums:

- SensorNode: `9524C76F78F62827603B6BA803A467161FD36481B80B7D6482B4A8D0AE83F066`
- LoRaGateway: `C21F048656D557028704827647C018912FD5E77CA8B5C1DE8BAC289295AE4C53`

Compilation and host-side protocol checks are complete. Final acceptance still requires an on-hardware bench test with the actual STM32 board, RS485 sensors, E32 modules, ESP8266, MQTT broker, and server.
