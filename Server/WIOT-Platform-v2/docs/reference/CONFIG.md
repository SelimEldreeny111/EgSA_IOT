# Configuration (environment variables)

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-15. Do not edit by hand._

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
| `WIOT_INGEST_BATCH_MS` | int | `0` | group-commit telemetry writes (250 recommended); 0 = off |
| `WIOT_MAINTENANCE_INTERVAL_S` | int | `600` | rollups, retention, status sampling |
| `WIOT_RETENTION_DAYS` | int | `0` | default raw-data retention per company; 0 = keep forever |
| `WIOT_STATUS_PUBLIC` | bool | `True` | public /status page (service health only, no company data) |
| `WIOT_CONFIG_WATCH` | bool | `True` | re-send SRATE/STRAN when a node reports other intervals than intended |
| `WIOT_PUBLIC_URL` | str \| None | — | e.g. https://wiot.example.org (links in e-mails, SSO redirect) |
| `WIOT_OIDC_ISSUER` | str \| None | — |  |
| `WIOT_OIDC_CLIENT_ID` | str \| None | — |  |
| `WIOT_OIDC_CLIENT_SECRET` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_OIDC_SCOPES` | str | `openid email profile` |  |
| `WIOT_OIDC_BUTTON_LABEL` | str | `Sign in with your organisation` |  |
| `WIOT_OIDC_AUTO_CREATE` | bool | `False` |  |
| `WIOT_OIDC_DEFAULT_ROLE` | Literal['admin', 'monitor', 'user'] | `user` |  |
| `WIOT_OIDC_DEFAULT_COMPANY` | str \| None | — |  |
| `WIOT_OIDC_ROLE_CLAIM` | str \| None | — |  |
| `WIOT_OIDC_COMPANY_CLAIM` | str \| None | — |  |
| `WIOT_OIDC_ALLOWED_DOMAINS` | list[str] | `[]` |  |
| `WIOT_SMTP_HOST` | str \| None | — |  |
| `WIOT_SMTP_PORT` | int | `587` |  |
| `WIOT_SMTP_USERNAME` | str \| None | — |  |
| `WIOT_SMTP_PASSWORD` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_SMTP_FROM` | str \| None | — |  |
| `WIOT_SMTP_SECURITY` | Literal['starttls', 'ssl', 'none'] | `starttls` |  |
| `WIOT_REPORTS_AUTO` | bool | `True` | build last month's report for every company on the 1st (and e-mail it) |
| `WIOT_FORWARD_QUEUE_MAX` | int | `5000` | integrations: pending forwards kept in memory |
| `WIOT_SENTINEL_CLIENT_ID` | str \| None | — |  |
| `WIOT_SENTINEL_CLIENT_SECRET` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_SENTINEL_BASE_URL` | str | `https://sh.dataspace.copernicus.eu` |  |
| `WIOT_SENTINEL_TOKEN_URL` | str | `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token` |  |
| `WIOT_REGIONAL_MIN_FARMS` | int | `3` | areas with fewer farms are not shown (privacy) |
| `WIOT_SATELLITE_PROVIDER` | Literal['auto', 'sentinelhub', 'open', 'off'] | `auto` |  |
| `WIOT_SATELLITE_MAX_CLOUD` | float | `60` | scene cloud cover above this is not searched |
| `WIOT_SATELLITE_OPEN_MAX_SCENES` | int | `6` | passes read per farm and run (bounds the traffic) |
| `WIOT_EARTHSEARCH_URL` | str | `https://earth-search.aws.element84.com/v1` |  |
| `WIOT_CDSE_STAC_URL` | str | `https://stac.dataspace.copernicus.eu/v1` | Copernicus Data Space catalogue (public) |
| `WIOT_EUMETSAT_URL` | str | `https://api.eumetsat.int` |  |
| `WIOT_EUMETSAT_KEY` | str \| None | — (secret; set in `.env`) |  |
| `WIOT_EUMETSAT_SECRET` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_EO_DOWNLOAD_MAX_MB` | int | `200` |  |
| `WIOT_WEB_PUSH` | bool | `True` | alerts to installed dashboards / phones (VAPID key created in data/ on first use) |
| `WIOT_ASSISTANT_ENABLED` | bool | `False` |  |
| `WIOT_ASSISTANT_API_KEY` | pydantic.types.SecretStr \| None | — (secret; set in `.env`) |  |
| `WIOT_ASSISTANT_MODEL` | str | `claude-opus-5-5` |  |
| `WIOT_ASSISTANT_DAILY_SUMMARY` | bool | `True` |  |
| `WIOT_ASSISTANT_MAX_PER_HOUR` | int | `30` |  |
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
