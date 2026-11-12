# Configuration (environment variables)

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-12. Do not edit by hand._

All settings are environment variables with the `WIOT_` prefix, read by pydantic-settings from the process environment and `.env` (see `.env.example`). Secret values are never shown here.

| Variable | Type | Default | Notes |
|---|---|---|---|
| `WIOT_ENV` | Literal['development', 'production'] | `development` |  |
| `WIOT_HOST` | str | `127.0.0.1` |  |
| `WIOT_PORT` | int | `8000` |  |
| `WIOT_WORKERS` | int | `1` | MQTT ingestion is single-owner; keep 1 |
| `WIOT_LOG_LEVEL` | Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] | `INFO` |  |
| `WIOT_LOG_JSON` | bool | `False` |  |
| `WIOT_TIMEZONE` | str | `Africa/Cairo` |  |
| `WIOT_DATA_DIR` | pathlib.Path | `D:\WorkSpace\EgSA\R&D_WS\IOT\WIOT Server\WIOT_Final_PowerModes_20261001\Server\WIOT-Platform-v2\data` |  |
| `WIOT_ANALYTICS_DIR` | pathlib.Path \| None | — |  |
| `WIOT_ANALYTICS_DATA_DIR` | pathlib.Path \| None | — | source DBs for the pipeline (default: data_dir) |
| `WIOT_REPO_ROOT` | pathlib.Path \| None | — | project root, used by the analytics pipeline |
| `WIOT_SECRET_KEY` | pydantic.types.SecretStr | — (secret; set in `.env`) |  |
| `WIOT_TOKEN_TTL_MINUTES` | int | `720` |  |
| `WIOT_COOKIE_SECURE` | bool | `False` |  |
| `WIOT_LOGIN_MAX_ATTEMPTS` | int | `8` |  |
| `WIOT_LOGIN_WINDOW_SECONDS` | int | `300` |  |
| `WIOT_CORS_ORIGINS` | list[str] | `[]` |  |
| `WIOT_METRICS_PUBLIC` | bool | `True` |  |
| `WIOT_WEBHOOK_ALLOW_PRIVATE` | bool \| None | — |  |
| `WIOT_ALERT_MONITOR` | bool | `True` | fleet alerts every minute: offline, battery, flow, leak/no-flow, weather, events (hub + webhooks) |
| `WIOT_TLS_CERTFILE` | pathlib.Path \| None | — |  |
| `WIOT_TLS_KEYFILE` | pathlib.Path \| None | — |  |
| `WIOT_BACKUP_DIR` | pathlib.Path \| None | — | default: <data_dir>/backups |
| `WIOT_BACKUP_PASSWORD` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) | set to encrypt backups (AES-256-GCM); keep it outside the server |
| `WIOT_BACKUP_KEEP` | int | `14` |  |
| `WIOT_CLOCK_SYNC` | bool | `True` | queue STIME when a node's clock is unset or drifts (real nodes: next wake) |
| `WIOT_CLOCK_SYNC_DRIFT_S` | int | `120` |  |
| `WIOT_CLOCK_SYNC_MIN_INTERVAL_S` | int | `21600` |  |
| `WIOT_NIGHT_FLOW_HOURS` | str | — | e.g. "00-04" (company local time) enables the night-flow alert; empty = off |
| `WIOT_FROST_WARN_C` | float | `2.0` |  |
| `WIOT_HEAT_WARN_C` | float | `40.0` |  |
| `WIOT_ADMIN_PASSWORD` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_SUPERVISOR_PASSWORD` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_MONITOR_PASSWORD` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_MQTT_AUTOCONNECT` | bool | `False` |  |
| `WIOT_MQTT_HOST` | str | `broker.hivemq.com` |  |
| `WIOT_MQTT_PORT` | int | `1883` |  |
| `WIOT_MQTT_CLIENT_ID` | str | `wiot_platform` |  |
| `WIOT_MQTT_USERNAME` | str \| None | — |  |
| `WIOT_MQTT_PASSWORD` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_MQTT_AES_KEY_HEX` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_MAP_TILE_URL` | str | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` |  |
| `WIOT_MAP_LABELS_URL` | str \| None | `https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}` |  |
| `WIOT_MAP_ATTRIBUTION` | str | `Imagery © Esri, Maxar, Earthstar Geographics` |  |
| `WIOT_MAP_BACKDROP` | str | `22.2545,28.7215,15` | lat,lon,zoom behind the sign-in card |
| `WIOT_WEATHER_ENABLED` | bool | `True` |  |
| `WIOT_WEATHER_URL` | str | `https://api.open-meteo.com/v1/forecast` |  |
| `WIOT_SATELLITE_MSGS_PER_DAY` | int | `48` |  |
| `WIOT_AUTOMATION_MIN_INTERVAL_S` | int | `120` |  |
