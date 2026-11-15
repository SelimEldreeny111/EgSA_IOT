"""Typed runtime configuration loaded from environment variables and ``.env``.

Every setting uses the ``WIOT_`` prefix (for example ``WIOT_PORT=8000``).
Secrets are ``SecretStr`` so they never appear in logs, reprs or the
``/api/v2/system/info`` endpoint.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WIOT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- runtime -----------------------------------------------------------
    env: Literal["development", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    workers: int = Field(1, ge=1, le=1, description="MQTT ingestion is single-owner; keep 1")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False
    timezone: str = "Africa/Cairo"

    # --- storage -----------------------------------------------------------
    data_dir: Path = PROJECT_DIR / "data"
    analytics_dir: Path | None = None
    analytics_data_dir: Path | None = None  # source DBs for the pipeline (default: data_dir)
    repo_root: Path | None = None  # project root, used by the analytics pipeline

    # --- security ----------------------------------------------------------
    secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(48)),
        validation_alias=AliasChoices("WIOT_SECRET_KEY", "WIOT_FLASK_SECRET_KEY"),
    )
    token_ttl_minutes: int = Field(12 * 60, ge=5, le=7 * 24 * 60)
    cookie_secure: bool = False
    login_max_attempts: int = Field(8, ge=1)
    login_window_seconds: int = Field(300, ge=10)
    cors_origins: list[str] = []
    metrics_public: bool = True
    # Webhooks to private/loopback addresses (SSRF risk). Default: allowed only in development.
    webhook_allow_private: bool | None = None
    alert_monitor: bool = True  # fleet alerts every minute: offline, battery, flow, leak/no-flow, weather, events (hub + webhooks)
    # TLS served directly by the platform (instead of a reverse proxy); both paths must be set.
    tls_certfile: Path | None = None
    tls_keyfile: Path | None = None
    # Backups (python -m wiot backup): point backup_dir at an off-site folder (network share, synced drive).
    backup_dir: Path | None = None  # default: <data_dir>/backups
    backup_password: SecretStr | None = None  # set to encrypt backups (AES-256-GCM); keep it outside the server
    backup_keep: int = Field(14, ge=1, le=365)

    # --- field operations (R2.1) --------------------------------------------
    clock_sync: bool = True  # queue STIME when a node's clock is unset or drifts (real nodes: next wake)
    clock_sync_drift_s: int = Field(120, ge=10, le=86400)
    clock_sync_min_interval_s: int = Field(6 * 3600, ge=600, le=7 * 86400)
    night_flow_hours: str = ""  # e.g. "00-04" (company local time) enables the night-flow alert; empty = off
    frost_warn_c: float = Field(2.0, ge=-20, le=15)
    heat_warn_c: float = Field(40.0, ge=25, le=60)

    # --- operations and data platform (R2.2) --------------------------------
    ingest_batch_ms: int = Field(0, ge=0, le=5000)  # group-commit telemetry writes (250 recommended); 0 = off
    maintenance_interval_s: int = Field(600, ge=30, le=86400)  # rollups, retention, status sampling
    retention_days: int = Field(0, ge=0, le=36500)  # default raw-data retention per company; 0 = keep forever
    status_public: bool = True  # public /status page (service health only, no company data)
    config_watch: bool = True  # re-send SRATE/STRAN when a node reports other intervals than intended

    # --- security, notifications, reports, integrations (R2.3) ---------------
    public_url: str | None = None  # e.g. https://wiot.example.org (links in e-mails, SSO redirect)
    # OpenID Connect single sign-on (Entra ID, Google, Keycloak, Okta ...); off until issuer + client id are set
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_scopes: str = "openid email profile"
    oidc_button_label: str = "Sign in with your organisation"
    oidc_auto_create: bool = False
    oidc_default_role: Literal["admin", "monitor", "user"] = "user"
    oidc_default_company: str | None = None
    oidc_role_claim: str | None = None
    oidc_company_claim: str | None = None
    oidc_allowed_domains: list[str] = []
    # Outgoing e-mail (alerts, invitations, monthly reports)
    smtp_host: str | None = None
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    reports_auto: bool = True  # build last month's report for every company on the 1st (and e-mail it)
    forward_queue_max: int = Field(5000, ge=100, le=100000)  # integrations: pending forwards kept in memory

    # --- crop records, satellite, regional views (R2.5) -----------------------
    # Copernicus Data Space Ecosystem (Sentinel Hub APIs) OAuth client; Sentinel-2 NDVI is off until set
    sentinel_client_id: str | None = None
    sentinel_client_secret: SecretStr | None = None
    sentinel_base_url: str = "https://sh.dataspace.copernicus.eu"
    sentinel_token_url: str = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    regional_min_farms: int = Field(3, ge=1, le=100)  # areas with fewer farms are not shown (privacy)

    # --- Earth observation (R2.7) ----------------------------------------------
    # Where field NDVI comes from: "auto" = Sentinel Hub when the OAuth client above is set, otherwise none;
    # "open" = the open Sentinel-2 archive on AWS (Earth Search, no account; needs numpy); "off" = never.
    satellite_provider: Literal["auto", "sentinelhub", "open", "off"] = "auto"
    satellite_max_cloud: float = Field(60, ge=0, le=100)  # scene cloud cover above this is not searched
    satellite_open_max_scenes: int = Field(6, ge=1, le=60)  # passes read per farm and run (bounds the traffic)
    earthsearch_url: str = "https://earth-search.aws.element84.com/v1"
    cdse_stac_url: str = "https://stac.dataspace.copernicus.eu/v1"  # Copernicus Data Space catalogue (public)
    # EUMETSAT Data Store: search is public; downloads need the API key from https://api.eumetsat.int/api-key
    eumetsat_url: str = "https://api.eumetsat.int"
    eumetsat_key: str | None = None
    eumetsat_secret: SecretStr | None = None
    eo_download_max_mb: int = Field(200, ge=1, le=5000)

    # --- field apps, maintenance, assistant (R2.6) ----------------------------
    web_push: bool = True  # alerts to installed dashboards / phones (VAPID key created in data/ on first use)
    # Optional AI assistant (Claude); off until enabled, needs the "assistant" extra and an Anthropic API key
    assistant_enabled: bool = False
    assistant_api_key: SecretStr | None = None
    assistant_model: str = "claude-opus-5-5"
    assistant_daily_summary: bool = True
    assistant_max_per_hour: int = Field(30, ge=1, le=1000)

    # Bootstrap accounts (same variable names as v1.31). Only used to create
    # missing built-in users; existing password hashes are never overwritten.
    admin_password: SecretStr | None = None
    supervisor_password: SecretStr | None = None
    monitor_password: SecretStr | None = None

    # --- MQTT ingestion ----------------------------------------------------
    mqtt_autoconnect: bool = False
    mqtt_host: str = "broker.hivemq.com"
    mqtt_port: int = Field(1883, ge=1, le=65535)
    mqtt_client_id: str = "wiot_platform"
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_aes_key_hex: SecretStr | None = None

    # --- smart agriculture -------------------------------------------------
    map_tile_url: str = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    map_labels_url: str | None = ("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/"
                                  "World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}")
    map_attribution: str = "Imagery © Esri, Maxar, Earthstar Geographics"
    map_backdrop: str = "22.2545,28.7215,15"  # lat,lon,zoom behind the sign-in card
    weather_enabled: bool = True
    weather_url: str = "https://api.open-meteo.com/v1/forecast"
    satellite_msgs_per_day: int = Field(48, ge=1, le=10000)
    automation_min_interval_s: int = Field(120, ge=10, le=86400)

    @field_validator("mqtt_aes_key_hex")
    @classmethod
    def _aes_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        raw = value.get_secret_value().strip()
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise ValueError("WIOT_MQTT_AES_KEY_HEX must be hex") from exc
        if len(key) != 16:
            raise ValueError("WIOT_MQTT_AES_KEY_HEX must be 32 hex characters (16 bytes)")
        return SecretStr(raw)

    @model_validator(mode="after")
    def _tls_pair(self) -> "Settings":
        if bool(self.tls_certfile) != bool(self.tls_keyfile):
            raise ValueError("Set both WIOT_TLS_CERTFILE and WIOT_TLS_KEYFILE, or neither")
        if self.tls_certfile:
            self.cookie_secure = True  # sessions over HTTPS only once TLS is on
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.env == "production":
            if len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("WIOT_SECRET_KEY must be set (>=32 chars) in production")
            if not self.cookie_secure:
                # Allowed behind a TLS-terminating proxy that sets it, but warn loudly.
                pass
        return self

    # --- derived paths -----------------------------------------------------
    @property
    def main_db(self) -> Path:
        return self.data_dir / "iot_data.db"

    @property
    def messages_dir(self) -> Path:
        return self.data_dir / "messages_dbs"

    @property
    def command_db(self) -> Path:
        return self.data_dir / "command_lifecycle.db"

    @property
    def legacy_command_db(self) -> Path:
        return self.data_dir / "pending_commands.db"

    @property
    def flash_db(self) -> Path:
        return self.data_dir / "flash_archive.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def analytics_path(self) -> Path:
        return self.analytics_dir or (self.data_dir / "analytics")

    @property
    def web_dir(self) -> Path:
        return PACKAGE_DIR / "web"

    def public_summary(self) -> dict:
        """Non-secret configuration for diagnostics."""
        return {
            "env": self.env,
            "timezone": self.timezone,
            "data_dir": str(self.data_dir),
            "analytics_dir": str(self.analytics_path),
            "mqtt": {
                "autoconnect": self.mqtt_autoconnect,
                "host": self.mqtt_host,
                "port": self.mqtt_port,
                "client_id": self.mqtt_client_id,
                "aes_key_configured": self.mqtt_aes_key_hex is not None,
                "auth": self.mqtt_username is not None,
            },
            "token_ttl_minutes": self.token_ttl_minutes,
            "cookie_secure": self.cookie_secure,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
