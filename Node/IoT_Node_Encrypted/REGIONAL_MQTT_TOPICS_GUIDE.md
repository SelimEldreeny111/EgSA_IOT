# Regional MQTT topics — STM32 node and web server

Release: 26 October 2026. Active Arduino STM32 node and Python web server.
The existing ESP32/CubeIDE ports and RS485 sensor simulators are unchanged.

## Configured bench identity

Company: `Company_1`; region: `Region_1`; node: `3`.
Identifiers are case-sensitive. The MQTT root and suffixes are lowercase.

| Purpose | Topic | Protobuf message |
|---|---|---|
| Telemetry and command replies | `wiot/Company_1/Region_1/3/data` | `Telemetry` |
| Periodic measurements/status | `wiot/Company_1/Region_1/3/status` | `Status_Message` |
| Direct commands | `wiot/Company_1/Region_1/3/cmd` | `CMD_Message` |
| Regional broadcast | `wiot/Company_1/Region_1/broadcast` | `CMD_Message` |

Broadcast has no node segment or final `/cmd`. It reaches the selected region,
not every region in the company. Reset-counter clears still reject broadcasts.
Protobuf field tags, encryption, watchdog behavior and command priority are
unchanged. Region is routing/storage identity outside the encrypted protobuf.

## Configure another device

In `src/config/AppConfig.h`, edit only the public identity macros:

```cpp
#define APP_MQTT_COMPANY "Company_1"
#define APP_MQTT_REGION "Region_1"
#define APP_NODE_ID 3
```

All six topic/prefix definitions and the MQTT client ID in the updated
`AppConfig.cpp` derive from these macros. Do not type a second independent node
ID in a topic string. `AppConfig.cpp.example` has the same definitions for a
fresh checkout; keep actual network credentials in the ignored local file.
Existing local files must use the updated macro-based topic definitions too.

Firmware company and region identifiers each support 1..24 ASCII letters,
digits, `_` or `-`. Empty strings, spaces, `/`, `+` and `#` fail compilation.
The server permits region identifiers up to 40 characters, but use the firmware
limit for deployed STM32 devices. Node IDs are canonical decimal 1..65535.
These bounds leave room for the 401-byte maximum encrypted telemetry frame
inside the existing 512-byte MQTT packet buffer.

## Server behavior

The ingestion subscriptions are:

```text
wiot/+/+/+/data
wiot/+/+/+/status
wiot/+/+/+/cmd
wiot/+/+/broadcast
```

The parser checks the exact structure, case and node/payload match. `/data`
decodes as `Telemetry`; `/status` decodes as `Status_Message`. Old `EgSA/...`
topics and old uppercase suffixes are not aliases in the updated web server.

The dashboard has a Region field next to Company. Select a discovered region or
enter a new valid one. Incoming data discovers regions automatically. Company
change resets selection to Region_1. Changing company/region stops periodic
STIME and clears the displayed node cache before loading the new scope.
Late API responses cannot replace another region's live/chart/timeline view.

Identity is `(company, region, node)`. Node 3 may exist in multiple regions:

- Latest readings, chart history, consumption periods and CSV filters include region.
- Retained WDT/power counters remain node-reported values in that same scope.
- Queued commands, replacement intents, regional broadcasts and matching ACKs
  include region. Region_1's Status cannot dispatch Region_2's pending command.
- WAKE tracking, map positions and browser threshold settings include region.
- User authorization remains company-based; an authorized company user can view
  that company's regions. This update does not introduce region-specific roles.

Example API request:

```json
{"company":"Company_1","region":"Region_1","node_id":3,
 "cmd_type":"GOSTM","cmd_data":0,"broadcast":false,"delivery":"now"}
```

The API defaults an omitted region to Region_1 for older local integrations;
new integrations should always provide it explicitly. GET filters use the same
`region=Region_1` query argument. Empty/invalid explicit regions are rejected.

## Existing databases and coordinated deployment

1. Keep a backup of the server databases before deploying the updated server.
   Do not delete the retained node flash records or databases for this change.
2. Stop the old server, then start the updated `server_web.py` from this final
   release directory using the established environment and passwords.
3. Startup migrates company message databases and the command journal. Existing
   rows/intents are assigned Region_1; this is an explicit legacy-data policy.
   Existing consumption rows are preserved and their unique key gains region.
   Review old pending commands before allowing a newly flashed node to connect.
4. Hard-refresh the browser with Ctrl+F5. As the supervisor, reconnect the broker
   and confirm all four new subscriptions. Select Company_1 / Region_1 / node 3.
5. Compile and flash the updated STM32 sketch. Node/server must both use this
   contract. An old running Python process does not load source edits by itself.
6. Confirm fresh `/status` traffic, then request GOSTM and confirm its `/data`
   response. Retained dashboard readings alone do not prove the new connection.

Automated verification uses temporary databases and broker fakes. Copies of
the existing company databases are migrated read-only through disposable
backups for preservation checks; production records are not changed by tests.

## LoRa gateway

A gateway belongs to one configured company/region. It forwards node status to
`.../{source_node}/status` and telemetry/replies to `.../{source_node}/data`.
It subscribes to `wiot/{company}/{region}/+/cmd` and the regional broadcast.
Its strict parser rejects other company/region prefixes and node-ID aliases.

The LoRa wire header has a network ID and node ID, not a region string. For
co-located regions, assign a distinct `APP_LORA_NETWORK_ID` to each region's
radio network, matching that region's gateway and nodes. Default Region_1 can
retain `0x4547`; a separate Region_2 installation could use `0x4548` after
confirming no collision with another local network. MQTT topic selection alone
does not separate radios using the same network/node identities.

## Acceptance tests

1. Verify Company_1 / Region_1 / node 3 status, sensor values, battery and both counters.
2. Send GOSTM, STIME and a harmless sampling/transmission-rate change. Check the
   correlated reply returns on `/data` and existing ACK configuration still applies.
3. In a controlled test, run node 3 in Region_2. Verify its values/charts do not
   replace Region_1/node 3. Check region-filtered history, CSV and consumption.
4. Queue a command in Region_2. A Region_1 Status must not send it. A Region_2
   Status should dispatch it; only a matching regional reply completes it.
5. Broadcast a harmless command in Region_1. Region_2 must not execute it.
6. Verify clear-counter commands remain direct-only and clear independently.
7. Repeat relevant tests on SIM, Wi-Fi, remote-wake and LoRa gateway profiles.
8. Restart the server and node; verify migration is idempotent and historical
   data, periods and retained counters remain available.

Valve commands should use the established commissioned bench procedure.
