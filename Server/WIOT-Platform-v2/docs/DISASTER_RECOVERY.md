# WIOT Platform — Disaster recovery

Targets: **RPO 24 h** (at most one day of server-side data lost; nodes keep up to weeks of samples in flash and
can be re-downloaded), **RTO 2 h** (service back on a replacement machine within two hours).

## What must be protected

| Item | Where | How it is protected |
|---|---|---|
| Databases (users, companies, alerts, audit, telemetry per company, command journal, flash archive) | `data/` | nightly `python -m wiot backup` (encrypted, consistent online copy) to an off-site `WIOT_BACKUP_DIR` |
| Configuration and secrets (`.env`: AES key, secret key, passwords) | server folder | kept **outside** the backups, in the organisation's password manager / sealed envelope |
| Backup password (`WIOT_BACKUP_PASSWORD`) | password manager | without it an encrypted backup cannot be restored |
| TLS certificate and key | `WIOT_TLS_CERTFILE/KEYFILE` | re-issue from the CA if lost |
| Node data not yet uploaded | node flash | Flash page → history download after the server is back |

## Routine (checked on the System health page)

* Backups: the **Backups** check turns amber when the newest backup is older than 36 h.
* Once a month: `python -m wiot verify-backup <newest .wbk>` on another machine, and a test restore (below)
  into an empty folder. Record the date in the operations log.
* Disk: the **Disk** check turns amber below 10 % free and red below 5 %.

## Scenarios

### 1. Server process crashed or was stopped
The Windows task (`deploy/windows/install-tasks.ps1`) or `systemd` (`deploy/wiot.service`) restarts it. Check
System health → Checks. Nodes keep their samples while the server is away; uplinks sent while the server was
down are not stored by the broker (QoS 0 public broker), so use the Flash page to recover gaps.

### 2. Database file damaged
1. Stop the server.
2. `python -m wiot check` and `sqlite3 <file> "PRAGMA integrity_check"` to identify the damaged file.
3. Restore the newest backup into a new folder: `python -m wiot restore-backup <file.wbk> --to D:\wiot-restore`.
4. Copy only the damaged database from the restored folder over the damaged one (keep the damaged copy aside).
5. Start the server; download node flash history for the period since the backup.

### 3. Machine lost (disk failure, theft, ransomware)
1. Install Python 3.12 and the platform on a replacement machine (`README.md` → Install).
2. Restore `.env` from the password manager (same `WIOT_MQTT_AES_KEY_HEX`, `WIOT_SECRET_KEY`, backup password).
3. `python -m wiot restore-backup <newest .wbk> --to <new data folder>`; set `WIOT_DATA_DIR` to it.
4. `python -m wiot check`, then start the server and the scheduled tasks.
5. Point DNS / the reverse proxy at the new machine; renew TLS if needed.
6. Download node flash history for the period since the backup (Flash page, one node at a time).
7. Users must sign in again (sessions are signed with the restored secret key, so existing sessions stay valid
   unless the key changed).

### 4. AES key or secret key compromised
1. Generate new keys; update `.env`.
2. Re-flash every node with the new AES key (field visit) — the server cannot rotate the node key remotely.
3. Changing `WIOT_SECRET_KEY` signs everyone out; revoke API tokens and create new ones.

### 5. Broker unavailable
The public broker is outside our control. Switch to the local Mosquitto bridge (`deploy/windows/mosquitto.conf`)
or another broker by changing `WIOT_MQTT_HOST`; gateways must use the same broker.

## Restore test record

| Date | Backup file | Restored by | Result |
|---|---|---|---|
| | | | |
