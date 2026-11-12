# Flash download diagnosis — bench procedure (R2.1, point 3; open issue OI-01)

**Goal.** Find where the per-row acknowledgements (HISTORY_ACK) of a flash history download are lost on the
way to a node sleeping in LORA_WOR_STOP. Uplinks are reliable; most ACK downlinks never reach the node, so
downloads end in *ACK timeout* (9 Nov 2026: the node sent row 1 three times and gave up).

**Needs:** the gateway on the bench with its USB serial port connected to a PC running a terminal program
that time-stamps every line (the one used on 9 Nov writes `11/9/2026 12:38:11.402 [RX] - ...`), node 2 in
LORA_WOR_STOP within radio range, the server and the broker bridge running, and about 20 minutes.
**Only the operator starts the download**: no other command may be sent to node 2 during the session.

## Steps

1. **Gateway logging.** Build or keep the gateway firmware with debug logging at INFO or higher
   (`DEBUG_LOGGING_GUIDE.md`). Open the serial port at 115200 baud and start saving the log to a file
   (for example `gateway-2026-11-xx.txt`). Check the PC clock against the server clock (same time zone).
2. **Quiet start.** On the Flash data page, confirm node 2 shows no *Node busy* strip. Note the local time.
3. **Status.** Press **Read status** once and wait for the reply (record count, RTC trusted).
4. **Download.** Press **Download today** right after the node's next Status uplink (the moment the node is
   awake). Do not press anything else while it runs.
5. **Wait** until the page shows the download as complete, stopped (*ACK timeout*) or stalled (6 minutes
   without progress). Note the end time. Stop saving the serial log.
6. **Timeline.** On the server PC, in `Server\WIOT-Platform-v2`:

   ```powershell
   .\.venv\Scripts\python -m wiot flash-timeline --company Company_1 --node 2 --since "2026-11-xx 10:00" --until "2026-11-xx 10:20" --gateway-log C:\path\gateway-2026-11-xx.txt
   ```

## Reading the result

The summary compares three counts for the window: `history_acks_published` (server), `history_acks_at_gateway`
(`command_rx ... HISTORY_ACK` in the gateway log) and `downlinks_transmitted` (`downlink_wake_complete probe=1
command=1`). The tool prints its reading; the cases are:

| Pattern | Where the ACKs are lost | Next step |
|---|---|---|
| Published > received at the gateway | Broker, bridge or the gateway's MQTT subscription | Check the bridge log and the gateway's subscription and keep-alive; test with the gateway on the local broker |
| Received > transmitted | Gateway radio path (AUX timeout, mode switch, busy with an uplink) | Look at the gateway log lines around each missing transmission |
| Transmitted, but the node resends the same row | Radio link or the node's wake timing (the first frame after a wake is consumed by the probe) | Firmware: a cumulative ACK every N rows, or a longer receive window after each row — needs a node firmware change |

Save the gateway log and the timeline output (`--json` for a machine-readable copy) with the date in
`Documentation/Validation/`, and add the finding to the open-issue list in `docs/HANDOFF.md`.
