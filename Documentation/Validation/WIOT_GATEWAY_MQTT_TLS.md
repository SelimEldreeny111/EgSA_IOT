# WIOT gateway and server MQTT TLS

The LoRa gateway selects its MQTT transport in the first block of
`Node/IoT_Node_Encrypted/src/config/AppConfig.h`. The Python server selects
its transport at startup. Plain MQTT remains the default for existing
installations. Set both ends to TLS for a TLS broker listener.

## Gateway firmware

```cpp
#define APP_MQTT_USE_TLS true
// Use the flag matching the ESP8266 firmware reported by AT+GMR.
#define APP_MQTT_TLS_ESP_LEGACY true
// Enable after installing the broker-only CA for SIM800L or legacy ESP8266.
#define APP_MQTT_TLS_DEDICATED_CA_PROVISIONED true
```

Build the LoRa gateway role with `USE_ESP8266` or `USE_SIM800`. Use the
broker DNS hostname and TLS listener port. Fresh TLS configurations default
to 8883. Check the saved host and port via the serial configuration console
on gateways already commissioned.

Use a listener with TLS 1.2 or newer. When it requires an MQTT username and
password, set `WIOT_MQTT_CREDENTIAL_HOST`, `WIOT_MQTT_USERNAME` and
`WIOT_MQTT_PASSWORD` in the local `AppSecrets.h`. The credential hostname
must match the commissioned broker hostname. Give the gateway and server
separate broker accounts with permissions for their WIOT topics.

| Modem | Trust setup |
|---|---|
| ESP8266 Non-OS AT 1.7.x | Provision the dedicated WIOT broker root in the ESP8266 CA flash area for its firmware and flash layout. Set `APP_MQTT_TLS_ESP_LEGACY=true` and confirm CA verification with `AT+CIPSSLCCONF`. |
| ESP8266 with newer ESP-AT | Provision the broker root in CA slot 0. Set `APP_MQTT_TLS_ESP_LEGACY=false`. The gateway enables CA verification and configures the broker name and SNI on socket 0. |
| SIM800L | Check the actual firmware revision with `ATI` or `AT+GMR` and secure TCP availability with `AT+CIPSSL=?`. Import the dedicated WIOT broker root using the SSL method supported by the module revision. The gateway requires `AT+SSLOPT=0,0` to succeed before opening a secure socket. |

For the legacy ESP8266 and SIM800L, use a private CA whose key signs only
the intended WIOT broker identity. These modem profiles rely on that
restricted trust root. Commission the modem with the broker-only root and
verify that its effective trust store rejects other issuers. In these profiles
the broker should present the intended certificate without relying on SNI.
Use the modem's provisioning tools to load the public root certificate.
The private signing key belongs in the certificate management environment.

The gateway applies the trust settings on each TLS connection. A rejected
configuration command or failed handshake leaves it disconnected. TLS mode
uses the secure modem socket for every connect attempt. The LoRa sensor node
sends its usual project payload to the gateway.

[ESP8266 Non-OS AT manual](https://www.espressif.com/sites/default/files/documentation/4a-esp8266_at_instruction_set_en.pdf)
· [ESP8266 ESP-AT socket commands](https://docs.espressif.com/projects/esp-at/en/release-v2.2.0.0_esp8266/AT_Command_Set/TCP-IP_AT_Commands.html)
· [SIMCom SSL application note](https://www.rbtronic.com.ua/simcom/2G/Application%20Notes/SIM800%20Series_SSL_Application%20Note_V1.05.pdf)

## Python server

Set `APP_MQTT_USE_TLS = True` near the top of `server_web.py` or set
`WIOT_MQTT_USE_TLS=true` in the server process environment. The environment
variable takes priority over the module setting. With TLS enabled, the broker
form starts at port 8883.

```powershell
$env:WIOT_MQTT_USE_TLS = 'true'
$env:WIOT_MQTT_BROKER_HOST = 'mqtt.example.com'
$env:WIOT_MQTT_CA_FILE = 'C:/wiot/certs/broker-root.pem'
python server_web.py
```

Set `WIOT_MQTT_USERNAME` and `WIOT_MQTT_PASSWORD` in the server's process
environment if the broker requires them. Paho verifies the certificate and
broker hostname. With `WIOT_MQTT_CA_FILE` empty, it uses the platform trust
store. Set the broker hostname to the name on its server certificate.
Use the existing Connect screen and application AES key.

## Test before switching the installation

1. Connect the Python server to a dedicated TLS test listener and wait for
   subscriptions to become ready. Check its TLS mode in Broker Configuration.
2. Cold-boot a test gateway with the intended modem. Confirm the modem's
   certificate validation and clock, where required. Verify a fresh heartbeat,
   LoRa telemetry uplink, and a server command with its node reply.
3. Temporarily select a test endpoint with an untrusted chain. Verify that
   each modem and the server reject it. Test a wrong hostname on ESP-AT
   with name checking and on the Python server.
4. Interrupt Wi‑Fi or cellular service, then restore it. Verify TLS
   reconnect, subscription recovery, and watchdog behavior on both modems.
5. To run plain lab MQTT again, select `false` for the gateway macro and
   the server setting. Use the plain listener port in the saved configuration.

Run `Validate-Release.ps1` for the AT-command and loopback TLS tests. Arduino
build profiles include `gateway-wifi-tls-legacy`, `gateway-wifi-tls`, and
`gateway-sim-tls`. These builds exercise compilation with the installed
Arduino libraries. Live TLS compatibility depends on the physical modem
firmware, certificate provisioning, and broker configuration.
