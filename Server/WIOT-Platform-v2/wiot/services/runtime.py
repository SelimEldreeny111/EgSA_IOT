"""Composition root: builds and owns every long-lived service."""
from __future__ import annotations

import json
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
from .confwatch import ConfigWatch
from .maintenance import Maintenance
from .nodehealth import NodeHealth
from .system import SystemService
from ..storage.notify_store import NotifyStore
from ..storage.security_store import SecurityStore
from .integrations import IntegrationService
from .notify import Notifier, RuleEngine
from .oidc import OidcClient
from .reports import ReportService
from .usage import UsageMeter
from .water import WaterService
from .cropcare import CropCare
from .regional import RegionalService
from .satellite import SatelliteService
from .assistant import Assistant
from .commissioning import Commissioning
from .maintenance_module import MaintenanceModule
from .push import PushService
from .webhooks import WebhookService
from .devices import DeviceService
from .greenhouse import GreenhouseService, GreenhouseStore

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.started_at = time.time()
        self.main = MainStore(settings.main_db)
        self.telemetry = TelemetryStore(settings.messages_dir, self.main.company_names, settings.ingest_batch_ms)
        self.hub = RealtimeHub()
        self.logs = LogBuffer(self.hub)
        self.broker = BrokerManager(self.hub, self.logs, on_plaintext=self._on_plaintext, on_json=self._on_json)
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
        self.confwatch = ConfigWatch(settings, self.commands, self.logs, self.main.audit)
        self.ingest.confwatch = self.confwatch
        self.commands.ack_listeners.append(self.confwatch.forget)
        self.node_health = NodeHealth(self.telemetry, self.commands, self.org, self.confwatch)
        self.system = SystemService(self)
        self.maintenance = Maintenance(settings, self.telemetry, self.main, self.org, self.system)
        # ---- R2.3: security, notifications, reports, usage, integrations
        secret = settings.secret_key.get_secret_value()
        self.security = SecurityStore(self.main, secret)
        self.oidc = OidcClient(settings)
        self.notify_store = NotifyStore(self.main, secret)
        private = self.webhooks.allow_private
        self.notifier = Notifier(settings, self.notify_store, allow_private=private)
        self.hub.listeners.append(self.notifier.on_event)
        self.rules = RuleEngine(self.notify_store)
        self.alerts.rules = self.rules
        self.reports = ReportService(settings, self.telemetry, self.org, self.alert_store, self.commands,
                                     branding=self.org.branding)
        self.usage = UsageMeter(self.main, self.telemetry)
        self.ingest.usage = self.usage
        self.commands.usage = self.usage
        self.integrations = IntegrationService(self.main, secret, allow_private=private,
                                               queue_max=settings.forward_queue_max)
        self.hub.listeners.append(self.integrations.on_event)
        self.maintenance.extra.append(self._maintenance_extra)
        # ---- R2.4: irrigation planning and water accounts
        self.water = WaterService(self.main, self.telemetry, self.farm, self.org, self.commands, self.logs, self.main.audit)
        self.farm.water = self.water
        self.alerts.company_hooks.append(self.water.check_alerts)
        # ---- R2.5: crop records, satellite, regional views
        self.cropcare = CropCare(self.main, self.telemetry, self.farm, self.water, self.org)
        self.satellite = SatelliteService(settings, self.main, self.telemetry, self.farm)
        self.regional = RegionalService(settings, self.main, self.org, self.farm, self.water, self.telemetry,
                                        self.alert_store, self.satellite)
        # ---- R2.6: phone app and push, commissioning, maintenance, assistant
        self.push = PushService(settings, self.main)
        if settings.web_push:
            self.hub.listeners.append(self.push.on_event)
        self.maint = MaintenanceModule(settings, self.main, self.main.audit)
        self.alerts.company_hooks.append(self.maint.check_alerts)
        self.commissioning = Commissioning(self.telemetry, self.org, self.commands, self.maint, self.main.audit)
        self.assistant = Assistant(settings, self)
        # ---- Track G: third-party devices (point 53) and greenhouse layouts (point 58)
        self.devices = DeviceService(self.main, self.telemetry, self.hub, self.logs, secret, self.main.company_names,
                                     alert_store=self.alert_store)
        self.devices.usage = self.usage
        self.devices.monitor = self.alerts
        self.alerts.company_hooks.append(self.devices.check_alerts)
        self.greenhouses = GreenhouseService(settings, GreenhouseStore(settings.main_db), self.telemetry, self.devices,
                                             self.farm, self.org)
        self.commands.power_mode = self.telemetry.latest_power_mode
        self.commands.risk = lambda c, r, n, t: self.analytics.predict_live(c, r, n, t)
        self.throttle = LoginThrottle(settings.login_max_attempts, settings.login_window_seconds)

    def _maintenance_extra(self, report: dict, daily: bool) -> None:
        if daily:
            for company in self.main.company_names():
                try:
                    deleted = self.devices.retention(company, self.maintenance.retention_days(company))
                    if deleted:
                        report.setdefault("device_readings_deleted", {})[company] = deleted
                except Exception:
                    log.exception("Device reading retention failed for %s", company)
            self.usage.backfill()
        self.usage.flush()
        self.integrations.flush_stats()
        for company in self.main.company_names():
            try:
                self.cropcare.record_weather(company)
                if daily:
                    self.satellite.fetch_ndvi(company)
            except Exception:
                log.exception("Crop weather / satellite update failed for %s", company)
        if daily:
            built = self.assistant.run_daily()
            if built:
                report["assistant_summaries"] = built
        if daily and self.settings.reports_auto:
            built = self.reports.auto_monthly(self.main.company_names(), self.notifier)
            if built:
                report["reports_built"] = built

    def store_satellite_record(self, rec: dict, pass_id: str) -> None:
        """One node reading delivered by a WIOT-SAT pass (R2.5): stored like an uplink, marked satellite."""
        from ..protocol.topics import region_id
        from ..protocol.validation import company_id
        from ..storage.telemetry_store import MESSAGE_COLUMNS
        company = rec["company"]
        company_id(company)
        region = region_id(rec.get("region") or "Region_1")
        node = int(rec["node_id"])
        if not 1 <= node <= 65535:
            raise ValueError("node_id out of range")
        measured = int(rec["measured_at"])
        now = int(time.time())
        if not now - 400 * 86400 < measured <= now + 600:
            raise ValueError("measured_at out of range")
        kind = rec.get("type") or "Status"
        if kind not in ("Status", "Telemetry"):
            raise ValueError("type must be Status or Telemetry")
        skip = {"timestamp", "type", "node_id", "company", "region", "measured_at", "time_source", "details"}
        fields = {k: v for k, v in (rec.get("fields") or {}).items()
                  if k in MESSAGE_COLUMNS and k not in skip and isinstance(v, (int, float)) and not isinstance(v, bool)}
        fields.update(measured_at=measured, time_source="satellite",
                      details=json.dumps({"via": "satellite", "pass": pass_id}))
        self.telemetry.save_message(company=company, region=region, received_at=now, msg_type=kind, node_id=node,
                                    sensor_id=str(rec.get("sensor_id") or 1), fields=fields)
        self.usage.count(company, "messages")

    def _on_plaintext(self, topic: str, plaintext: bytes) -> None:
        self.ingest.on_plaintext(topic, plaintext)

    def _on_json(self, topic: str, payload: bytes) -> None:
        self.devices.on_mqtt(topic, payload)

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
        self.system.init_schema()
        self.security.init_schema()
        self.notify_store.init_schema()
        self.usage.init_schema()
        self.integrations.init_schema()
        self.water.init_schema()
        self.cropcare.init_schema()
        self.satellite.init_schema()
        self.push.init_schema()
        self.maint.init_schema()
        self.assistant.init_schema()
        self.devices.init_schema()
        self.greenhouses.init_schema()
        if self.devices.seed_demo(self.main.company_names()) | self.greenhouses.seed_demo(self.main.company_names()):
            log.info("Seeded demo greenhouses and third-party devices for Demo_AgriFarm")
        if s.web_push:
            self.push.start()
        self.notifier.start()
        self.integrations.start()
        self.maintenance.start()
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
        self.maintenance.stop()
        self.telemetry.close()  # commit queued telemetry (batched writes) before exit
        self.broker.disconnect(quiet=True)
        log.info("WIOT Platform stopped")
