# WIOT MQTT and LoRa delivery

## Deploy

Restart the Python server with the updated code before flashing the gateway.
The existing command, data, and status topics and the V1 encrypted frame
format still apply. Brokers with topic ACLs must allow the gateway to publish
`wiot/{company}/{region}/gateway/{id}/event` and subscribe to
`wiot/{company}/{region}/+/receipt` at QoS 1. The server subscribes to gateway
events and publishes encrypted persistence receipts on
`wiot/{company}/{region}/{node}/receipt`. Operator commands remain non-retained.

The gateway waits for matching QoS 1 SUBACKs for direct, broadcast, and receipt
subscriptions. It buffers a complete MQTT packet before decoding. A read or
framing fault closes the session. The codec applies and validates PKCS#7 once,
around the AES CBC primitive. The server and gateway log a fingerprint of
the exact encrypted MQTT frame. Compare fingerprints together with topic and
length. A fingerprint is diagnostic evidence, not an authentication tag.

## Radio profiles

- Start with `APP_LORA_COORDINATED=0` on gateway and nodes. This mode accepts
  the existing wire framing, queues downlinks, and defers command transmission
  during an active reception. Independent nodes can still contend on air.
- For a shared channel, build all participants with `APP_LORA_COORDINATED=1`.
  Set `APP_LORA_COORDINATED_NODES` on the gateway to the unique deployed IDs.
  Set `APP_LORA_GRANT_POLL_MS` to a per-node polling interval appropriate to
  the measured cycle time. The default is 30000 ms. Sampling keeps its own
  SRATE deadline. Due Status and flash records wait for granted capacity.
  The gateway gives a direct command a reply window and gives routine
  traffic a turn between groups of commands. Use direct commands in this
  profile. Regional broadcasts are reported as radio dispatch failures.
- For WOR nodes, enable the gateway's Mode-1 wake transmission
  (`APP_LORA_GATEWAY_WOR_TX=1` or its active runtime equivalent).
  Measure current and command-window latency on the deployed radios. Shared
  wake preambles can wake non-target nodes briefly.

Coordinated acknowledgments use a 2500 ms fragment wait and omit in-window
retries on the first fragment. A node can retry one failed correlated reply
on later grants without reapplying its command. Final fragment acknowledgment
on the gateway requires full CRC verification and an admitted application
queue entry. Lost final ACKs are handled by a bounded duplicate cache.

The gateway coalesces Status per node. Correlated replies remain in a bounded
RAM queue across broker disconnects and are retried until an exact server
receipt or five-minute expiry. Server receipts are sent after durable
persistence. The gateway queue is lost on reset; absence of a reply leaves
execution uncertain. Server command deadlines use gateway evidence when it
arrives and remain capped by the server intent expiry. Commands expire after
60 seconds in the gateway queue. A newer value command replaces an older
matching command that is still queued. A transmitted valve command is never
automatically dispatched again by the server.

## Bench acceptance

1. Start with the same AES key and company/region on server, gateway, and node.
   Send sequential and back-to-back GOSTM requests. Compare command wire
   fingerprints and follow the server timeline through gateway receipt, radio
   dispatch, and the node's result. Repeat after an MQTT reconnect.
2. In an isolated broker fixture, send a command with a different synthetic
   key. Check that the server records the gateway decode failure for the
   matching wire fingerprint. Verify that the next valid command succeeds.
3. Start a node Status and issue FLASH_STATUS before it finishes. Check that
   downlink waits, the gateway accepts the reply once, and the dashboard
   reaches a terminal state after persistence. Disconnect MQTT after radio
   receipt and reconnect before the five-minute reply expiry.
4. Enable coordinated mode across the channel for two nodes, then three. Use
   synchronized report deadlines and send GOSTM and FLASH_TODAY during the
   run. Compare radio retries and command latency with the legacy profile.
   Verify every node gets a grant, flash history yields between records,
   and WOR current returns to the measured baseline between windows.

Host checks exercise MQTT staging, QoS subscription readiness, scoped wire
correlation, final-fragment CRC/ACK timing, duplicate suppression and gateway
grant pacing. Physical RF airtime, WOR current, and modem behavior require a
bench capture.
