"""Composition root: builds and owns every long-lived service."""
from __future__ import annotations

import logging
import time

from ..config import Settings
from ..security import LoginThrottle
from ..storage.alert_store import AlertStore
from ..storage.main_store import MainStore
from ..storage.org_store import OrgStore
from ..storage.telemetry_store import TelemetryStore
from .analytics import AnalyticsService
from .broker import BrokerManager, BrokerParams
from .commands import CommandService
from .farm import FarmService, FarmStore, WeatherClient
from .ingest import IngestService
from .realtime import LogBuffer, RealtimeHub
from .alerts import AlertMonitor
from .clocksync import ClockSync
from .webhooks import WebhookService

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.started_at = time.time()
        self.main = MainStore(settings.main_db)
        self.telemetry = TelemetryStore(settings.messages_dir, self.main.company_names)
        self.hub = RealtimeHub()
        self.logs = LogBuffer(self.hub)
        self.broker = BrokerManager(self.hub, self.logs, on_plaintext=self._on_plaintext)
        self.commands = CommandService(
            settings.command_db, settings.legacy_command_db, self.broker, self.hub, self.logs,
            history_writer=self._write_command_history)
        self.ingest = IngestService(self.telemetry, self.commands, self.hub, self.logs,
                                    settings.flash_db, self.main.company_names)
        self.commands.flash_transfer = self.ingest.flash.active_transfer  # one flash conversation per node
        self.analytics = AnalyticsService(settings, self.telemetry)
        self.farm = FarmService(settings, FarmStore(settings.main_db), self.telemetry, WeatherClient(settings))
        self.farm.commands, self.farm.logs, self.farm.hub, self.farm.audit = (
            self.commands, self.logs, self.hub, self.main.audit)
        self.ingest.farm = self.farm
        self.org = OrgStore(self.main)
        self.ingest.org = self.org
        self.commands.node_type = self.farm.node_type = self.org.node_type  # valve control only on control nodes
        allow_private = settings.webhook_allow_private
        self.webhooks = WebhookService(self.org, allow_private=settings.env == "development" if allow_private is None
                                       else allow_private)
        self.hub.listeners.append(self.webhooks.on_event)
        self.alert_store = AlertStore(settings.main_db)
        self.alerts = AlertMonitor(self.telemetry, self.org, self.hub, self.main.company_names, self.alert_store,
                                   settings=settings)
        self.alerts.farm = self.farm
        self.ingest.alerts = self.alerts
        self.clock_sync = ClockSync(settings, self.commands, self.logs, self.main.audit)
        self.ingest.clock = self.clock_sync
        self.commands.power_mode = self.telemetry.latest_power_mode
        self.commands.risk = lambda c, r, n, t: self.analytics.predict_live(c, r, n, t)
        self.throttle = LoginThrottle(settings.login_max_attempts, settings.login_window_seconds)

    def _on_plaintext(self, topic: str, plaintext: bytes) -> None:
        self.ingest.on_plaintext(topic, plaintext)

    def _write_command_history(self, company, region, node_id, details, request_id) -> None:
        self.ingest.write_command_history(company, region, node_id, details, request_id)

    # ------------------------------------------------------------- lifecycle
    def startup(self) -> None:
        s = self.settings
        s.data_dir.mkdir(parents=True, exist_ok=True)
        self.main.init_schema()
        self.org.init_schema()
        self.alert_store.init_schema()
        created = self.main.bootstrap_users(
            s.admin_password.get_secret_value() if s.admin_password else None,
            s.supervisor_password.get_secret_value() if s.supervisor_password else None,
            s.monitor_password.get_secret_value() if s.monitor_password else None,
        )
        if created:
            log.info("Created built-in accounts: %s", ", ".join(created))
        issues = self.telemetry.preflight()
        if issues:
            raise RuntimeError(f"Tenant database collision; run `python -m wiot check`: {issues}")
        for company in self.main.company_names():
            self.telemetry.ensure(company)
        self.farm.store.init_schema()
        if self.farm.store.seed_demo(self.main.company_names()):
            log.info("Seeded demo farm layout for Demo_AgriFarm")
        _ = self.commands.journal  # open/upgrade the journal eagerly so failures surface at boot
        if s.alert_monitor:
            self.alerts.start()
        self.logs.emit(f"WIOT Platform started; tenants={', '.join(self.main.company_names())}")
        if s.mqtt_autoconnect:
            if s.mqtt_aes_key_hex is None:
                self.logs.emit("[MQTT] Autoconnect skipped: WIOT_MQTT_AES_KEY_HEX is not set", level="warning")
            else:
                try:
                    self.broker.connect(BrokerParams(
                        host=s.mqtt_host, port=s.mqtt_port, client_id=s.mqtt_client_id,
                        aes_key=bytes.fromhex(s.mqtt_aes_key_hex.get_secret_value()),
                        username=s.mqtt_username,
                        password=s.mqtt_password.get_secret_value() if s.mqtt_password else None))
                except Exception:
                    log.exception("MQTT autoconnect failed; paho will not retry an initial failure")

    def shutdown(self) -> None:
        self.alerts.stop()
        self.broker.disconnect(quiet=True)
        log.info("WIOT Platform stopped")
