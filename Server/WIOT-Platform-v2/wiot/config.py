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
