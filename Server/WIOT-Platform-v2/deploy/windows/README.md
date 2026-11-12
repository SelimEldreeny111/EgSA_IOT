# Production on Windows — service, HTTPS, broker, backups (R2.1, points 4–6)

These steps turn a Windows PC or server into a production host. Each step changes the machine, so an
administrator runs them; nothing here is run automatically. Linux and Docker users have
`docker-compose.yml`, `deploy/wiot.service` and `deploy/nginx.conf` instead.

## 0. Prerequisites

- Windows 10/11 or Windows Server with the project folder and its `.venv` (see the main README).
- `.env` with real secrets: `WIOT_SECRET_KEY` (≥ 32 characters), `WIOT_ENV=production`, the account passwords,
  and `WIOT_MQTT_AES_KEY_HEX` equal to the nodes' firmware key. Never commit `.env`.

## 1. Broker — Eclipse Mosquitto with a bridge to HiveMQ (point 5)

1. Download the Windows installer from <https://mosquitto.org/download/> and install it with the
   **Service** option.
2. Create `C:\ProgramData\mosquitto\`, copy `deploy\windows\mosquitto.conf` over
   `C:\Program Files\mosquitto\mosquitto.conf` (keep the original), and change `remote_clientid` to a value
   unique to this installation.
3. Restart the service: `Restart-Service mosquitto`.
4. In `.env`: `WIOT_MQTT_HOST=127.0.0.1`, `WIOT_MQTT_PORT=1883`, `WIOT_MQTT_AUTOCONNECT=true`.
5. Check: the platform's `/readyz` reports the broker ready, and node data from the field appears.

The gateways keep publishing to `broker.hivemq.com`; only `wiot/Company_1/#` (add more companies in the file) is
bridged. Moving the gateways to a private broker needs a firmware change and is not part of this release.

## 2. HTTPS (point 4)

Either serve TLS from the platform itself or put it behind the nginx proxy in `deploy/nginx.conf`.

- **Platform TLS:** obtain a certificate for the server's DNS name (from EgSA IT, or Let's Encrypt with
  a client such as win-acme if the host is reachable from the Internet on port 80), save the PEM files, and set
  `WIOT_TLS_CERTFILE`, `WIOT_TLS_KEYFILE`, `WIOT_HOST=0.0.0.0` and `WIOT_PORT=443` in `.env`. Setting the TLS
  files also switches session cookies to *Secure*.
- **Firewall:** allow inbound TCP 443 only from the networks that need the dashboard:
  `New-NetFirewallRule -DisplayName "WIOT HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow`.

## 3. Run as a service with automatic restart (point 4)

From an elevated PowerShell in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-tasks.ps1
Start-ScheduledTask -TaskPath '\WIOT\' -TaskName 'WIOT Platform'
```

This registers `\WIOT\WIOT Platform` (starts at boot, restarts every minute if it stops, no time limit) and
`\WIOT\WIOT Backup` (nightly at 02:00). `uninstall-tasks.ps1` removes both. Stop the development processes
(`run-dev.ps1`, `devbroker`, `simulate`) first: only one server may own MQTT ingestion.

## 4. Backups and a tested restore (point 6)

- In `.env`: `WIOT_BACKUP_DIR` = an off-site folder (network share or a synced drive), `WIOT_BACKUP_PASSWORD`
  = a long password stored also outside the server (without it the backups cannot be read),
  `WIOT_BACKUP_KEEP=14`.
- Manual run: `.\.venv\Scripts\python -m wiot backup` → `wiot-backup-<date>.wbk` (AES-256-GCM encrypted).
- Verify any backup: `.\.venv\Scripts\python -m wiot verify-backup <file>` (checks every database's digest and
  integrity).
- **Restore test (monthly):** `.\.venv\Scripts\python -m wiot restore-backup <file> --to D:\wiot-restore-test`,
  then start a second copy of the server on another machine with `WIOT_DATA_DIR` pointing there and check the
  dashboard. Restore never writes over a non-empty folder.

## 5. Acceptance checklist for R2.1 operations

| Check | How |
|---|---|
| Survives reboot | Restart the machine; the dashboard is back without anyone logging in |
| Restarts after a crash | End the `python` process in Task Manager; it is back within a minute |
| HTTPS | Browser shows a valid certificate; `http://` is not offered on the network |
| Broker | `/readyz` ready; field data arrives; Mosquitto log shows the bridge connected |
| Backup | A `.wbk` file appears nightly in the off-site folder |
| Restore | `verify-backup` passes and a restored copy opens on a second machine |
