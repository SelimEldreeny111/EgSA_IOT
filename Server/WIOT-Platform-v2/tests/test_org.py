"""Organization registry, API tokens, webhooks, strict provisioning and the world view."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import PASSWORDS, login
from wiot.protocol import messages_pb2

API = "/api/v2"


def _status(node: int) -> bytes:
    return messages_pb2.Status_Message(
        node_id=node, sensor_id=1, timestamp=int(time.time()), battery_voltage=3.9, sensor_mask=3,
        active_sensor_count=2, flow_meter_type=1, flow_live_valid=True, rtc_valid=True, flow_period_quality=1,
        flow_rate=0.0, soil_moisture=30.0, soil_temperature=24.0, soil_moisture_temp_valid=1,
        node_status=0, power_mode=2, power_state=1).SerializeToString()


def _admin_client(supervisor):
    """Create an admin user for Company_1 and return a second, logged-in client."""
    from fastapi.testclient import TestClient
    r = supervisor.post(f"{API}/users", json={"username": "c1_admin", "password": "Admin-pass-456",
                                              "role": "admin", "company": "Company_1"})
    assert r.status_code == 201, r.text
    c = TestClient(supervisor.app)
    c.headers["X-CSRF-Token"] = login(c, "c1_admin", "Admin-pass-456")
    return c


def test_company_profile_create_update_archive(supervisor, app):
    r = supervisor.post(f"{API}/org/companies", json={"name": "Nile_Farms", "display_name": "Nile Farms Co.",
                                                      "country": "eg", "timezone": "Africa/Cairo", "units": "metric",
                                                      "language": "ar", "lat": 30.05, "lon": 31.6})
    assert r.status_code == 201, r.text
    assert r.json()["country"] == "EG" and r.json()["language"] == "ar"
    names = [c["name"] for c in supervisor.get(f"{API}/companies").json()["companies"]]
    assert "Nile_Farms" in names
    bad = supervisor.patch(f"{API}/org/companies/Nile_Farms", json={"timezone": "Mars/Olympus"})
    assert bad.status_code == 400 and "time zone" in bad.json()["detail"]
    ok = supervisor.patch(f"{API}/org/companies/Nile_Farms", json={"units": "imperial", "timezone": "America/Chicago"})
    assert ok.json()["units"] == "imperial" and ok.json()["timezone"] == "America/Chicago"
    # archive: hidden from the tenant switcher and ingest drops its frames
    assert supervisor.patch(f"{API}/org/companies/Nile_Farms", json={"active": False}).json()["active"] is False
    assert "Nile_Farms" not in [c["name"] for c in supervisor.get(f"{API}/companies").json()["companies"]]
    assert "Nile_Farms" in [c["name"] for c in supervisor.get(f"{API}/org/companies").json()["companies"]]
    app.state.runtime.ingest.on_plaintext("wiot/Nile_Farms/Region_1/1/status", _status(1))
    supervisor.patch(f"{API}/org/companies/Nile_Farms", json={"active": True})
    assert supervisor.get(f"{API}/fleet", params={"company": "Nile_Farms"}).json()["nodes"] == []


def test_regions_nodes_gateways_and_csv(supervisor, app):
    q = {"company": "Company_1"}
    r = supervisor.post(f"{API}/org/regions", params=q, json={"region": "Delta_North", "display_name": "Delta North",
                                                              "country": "EG", "lat": 31.1, "lon": 30.9})
    assert r.status_code == 201, r.text
    assert "Delta_North" in supervisor.get(f"{API}/regions", params=q).json()["regions"]
    assert supervisor.post(f"{API}/org/regions", params=q, json={"region": "Delta_North"}).status_code == 400
    g = supervisor.post(f"{API}/org/gateways", params=q, json={"gw_id": "GW-7", "name": "North gateway",
                                                               "region": "Delta_North", "backhaul": ["lora", "cellular", "satellite"]})
    assert g.status_code == 201 and g.json()["primary"] == "cellular"
    n = supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Delta_North", "node_id": 12, "name": "Pivot 12 probe",
                                                            "kind": "soil_flow", "gateway": "GW-7", "lat": 31.1, "lon": 30.9,
                                                            "install_date": "2026-10-01", "report_interval_s": 300})
    assert n.status_code == 201, n.text
    assert supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Delta_North", "node_id": 12}).status_code == 400
    assert supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Delta_North", "node_id": 13,
                                                               "kind": "rocket"}).status_code == 400
    # region with registered nodes cannot be deleted
    assert supervisor.delete(f"{API}/org/regions/Delta_North", params=q).status_code == 400
    # CSV import: one update, one create, one error
    csv_text = ("region,node_id,name,kind,lat,lon,gateway,install_date,report_interval_s,notes\n"
                "Delta_North,12,Renamed probe,soil,,,,,,\n"
                "Delta_North,14,Valve 14,valve,31.2,30.8,GW-7,2026-10-02,600,\n"
                "Delta_North,99999,Bad,soil,,,,,,\n")
    res = supervisor.post(f"{API}/org/nodes/import", params=q, json={"csv": csv_text}).json()
    assert (res["created"], res["updated"], len(res["errors"])) == (1, 1, 1) and res["errors"][0]["line"] == 4
    nodes = supervisor.get(f"{API}/org/nodes", params=q).json()
    by = {(x["region"], x["node_id"]): x for x in nodes["nodes"]}
    assert by[("Delta_North", 12)]["name"] == "Renamed probe" and by[("Delta_North", 12)]["link_state"] == "pending"
    exported = supervisor.get(f"{API}/org/nodes/export.csv", params=q).text
    assert exported.splitlines()[0].startswith("region,node_id,name") and "Valve 14" in exported
    # telemetry from an unregistered node shows up as discovered; registered node gets its name on /fleet
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Delta_North/12/status", _status(12))
    rt.ingest.on_plaintext("wiot/Company_1/Delta_North/40/status", _status(40))
    nodes = supervisor.get(f"{API}/org/nodes", params=q).json()
    assert {(d["region"], d["node_id"]) for d in nodes["discovered"]} == {("Delta_North", 40)}
    fleet = supervisor.get(f"{API}/fleet", params={**q, "region": "Delta_North"}).json()
    assert {n["node_id"]: n["name"] for n in fleet["nodes"]}[12] == "Renamed probe"
    # move and delete
    supervisor.post(f"{API}/org/regions", params=q, json={"region": "Delta_South"})
    moved = supervisor.patch(f"{API}/org/nodes/Delta_North/14", params=q, json={"name": "Valve 14", "kind": "valve",
                                                                                 "new_region": "Delta_South"})
    assert moved.json()["region"] == "Delta_South"
    assert supervisor.delete(f"{API}/org/gateways/GW-7", params=q).status_code == 200
    assert supervisor.delete(f"{API}/org/nodes/Delta_South/14", params=q).status_code == 200


def test_strict_provisioning_drops_unregistered_nodes(supervisor, app):
    q = {"company": "Company_1"}
    rt = app.state.runtime
    supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Region_1", "node_id": 1, "kind": "soil"})
    assert supervisor.patch(f"{API}/org/companies/Company_1", json={"strict_nodes": True}).json()["strict_nodes"]
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/1/status", _status(1))
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", _status(2))
    seen = {n["node_id"] for n in supervisor.get(f"{API}/fleet", params=q).json()["nodes"]}
    assert seen == {1}
    supervisor.patch(f"{API}/org/companies/Company_1", json={"strict_nodes": False})
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", _status(2))
    assert {n["node_id"] for n in supervisor.get(f"{API}/fleet", params=q).json()["nodes"]} == {1, 2}


def test_admin_scope_and_monitor_read_only(supervisor):
    admin = _admin_client(supervisor)
    assert admin.post(f"{API}/org/regions", params={"company": "Company_1"}, json={"region": "R_A"}).status_code == 201
    assert admin.post(f"{API}/org/regions", params={"company": "Company_2"}, json={"region": "R_B"}).status_code == 403
    assert admin.post(f"{API}/org/companies", json={"name": "Rogue"}).status_code == 403
    assert admin.patch(f"{API}/org/companies/Company_1", json={"active": False}).status_code == 403
    assert admin.patch(f"{API}/org/companies/Company_1", json={"units": "imperial"}).status_code == 200
    from fastapi.testclient import TestClient
    mon = TestClient(supervisor.app)
    mon.headers["X-CSRF-Token"] = login(mon, "Super_User", PASSWORDS["WIOT_MONITOR_PASSWORD"])
    assert mon.get(f"{API}/org/regions", params={"company": "Company_1"}).status_code == 200
    assert mon.post(f"{API}/org/regions", params={"company": "Company_1"}, json={"region": "R_C"}).status_code == 403


def test_api_tokens_read_write_and_revoke(supervisor):
    from fastapi.testclient import TestClient
    q = {"company": "Company_1"}
    read = supervisor.post(f"{API}/org/tokens", params=q, json={"name": "BI dashboard", "scope": "read"}).json()
    write = supervisor.post(f"{API}/org/tokens", params=q, json={"name": "ERP", "scope": "write", "expires_days": 30}).json()
    assert read["token"].startswith("wiot_") and "token" not in supervisor.get(f"{API}/org/tokens", params=q).json()["tokens"][0]
    bot = TestClient(supervisor.app)  # no cookie, no CSRF: bearer only
    h = {"Authorization": f"Bearer {read['token']}"}
    assert bot.get(f"{API}/fleet", headers=h).json()["company"] == "Company_1"
    assert bot.get(f"{API}/fleet", params={"company": "Company_2"}, headers=h).status_code == 403
    assert bot.post(f"{API}/org/regions", headers=h, json={"region": "X"}).status_code == 403
    hw = {"Authorization": f"Bearer {write['token']}"}
    assert bot.post(f"{API}/org/regions", headers=hw, json={"region": "From_ERP"}).status_code == 201
    assert bot.post(f"{API}/org/tokens", headers=hw, json={"name": "escalate"}).status_code == 403
    assert bot.get(f"{API}/users", headers=hw).status_code == 403
    supervisor.delete(f"{API}/org/tokens/{read['id']}", params=q)
    assert bot.get(f"{API}/fleet", headers=h).status_code == 401
    assert bot.get(f"{API}/fleet", headers={"Authorization": "Bearer wiot_not-a-token"}).status_code == 401


class _Receiver(BaseHTTPRequestHandler):
    hits: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Receiver.hits.append(({k.lower(): v for k, v in self.headers.items()}, body))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture()
def receiver():
    _Receiver.hits = []
    srv = HTTPServer(("127.0.0.1", 0), _Receiver)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/hook", _Receiver.hits
    srv.shutdown()


def test_webhooks_are_signed_and_filtered(supervisor, app, receiver):
    url, hits = receiver
    q = {"company": "Company_1"}
    created = supervisor.post(f"{API}/org/webhooks", params=q, json={"name": "Ops", "url": url, "events": ["alert"]})
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    assert secret.startswith("whsec_") and "…" in supervisor.get(f"{API}/org/webhooks", params=q).json()["webhooks"][0]["secret"]
    ping = supervisor.post(f"{API}/org/webhooks/{created.json()['id']}/test", params=q).json()
    assert ping["status"] == 204 and ping["error"] is None
    rt = app.state.runtime
    rt.hub.publish("telemetry", {"node_id": 1}, company="Company_1")      # not subscribed
    rt.hub.publish("alert", {"kind": "node_offline", "node_id": 3}, company="Company_2")  # other tenant
    rt.hub.publish("alert", {"kind": "node_offline", "node_id": 1}, company="Company_1")
    deadline = time.time() + 5
    while len(hits) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert len(hits) == 2
    headers, body = hits[1]
    payload = json.loads(body)
    assert payload["event"] == "alert" and payload["data"]["node_id"] == 1 and payload["company"] == "Company_1"
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert headers["x-wiot-signature"] == expected and headers["x-wiot-event"] == "alert"
    assert supervisor.post(f"{API}/org/webhooks", params=q,
                           json={"name": "x", "url": "ftp://nope", "events": ["alert"]}).status_code == 400


def test_webhook_ssrf_guard_in_production():
    from wiot.services.webhooks import check_destination
    with pytest.raises(ValueError):
        check_destination("http://127.0.0.1:9/x", allow_private=False)
    with pytest.raises(ValueError):
        check_destination("http://10.0.0.5/x", allow_private=False)
    check_destination("http://127.0.0.1:9/x", allow_private=True)


def test_alert_monitor_fires_on_offline_transition(app, supervisor):
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/5/status", _status(5))
    rt.alerts.check()  # baseline
    key = ("Company_1", "Region_1", 5)
    rt.alerts.state[key] = "online"
    rt.telemetry.fleet = lambda c, r, _f=rt.telemetry.fleet: [{**n, "link_state": "offline"} for n in _f(c, r)]
    fired = rt.alerts.check()
    assert any(a["kind"] == "node_offline" and a["node_id"] == 5 for a in fired)


def test_world_view(supervisor, app):
    supervisor.patch(f"{API}/org/companies/Company_1", json={"country": "EG", "lat": 30.05, "lon": 31.6})
    supervisor.post(f"{API}/org/regions", params={"company": "Company_1"},
                    json={"region": "Space_City", "display_name": "EgSA Space City", "lat": 30.0498, "lon": 31.6071})
    app.state.runtime.ingest.on_plaintext("wiot/Company_1/Space_City/1/status", _status(1))
    w = supervisor.get(f"{API}/org/world").json()
    c1 = next(c for c in w["companies"] if c["name"] == "Company_1")
    site = next(s for s in c1["sites"] if s["region"] == "Space_City")
    assert site["name"] == "EgSA Space City" and site["online"] == 1 and site["located_by"] == "region"


def test_calendar_periods_use_company_timezone(supervisor, app):
    supervisor.patch(f"{API}/org/companies/Company_1", json={"timezone": "Pacific/Auckland"})
    assert app.state.runtime.org.timezone("Company_1") == "Pacific/Auckland"


def test_node_types_and_sensors(supervisor, app):
    q = {"company": "Company_1"}
    mon = supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Region_1", "node_id": 21, "node_type": "monitoring",
                                                             "sensors": ["hnda", "sondas"], "name": "Probe 21"})
    ctl = supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Region_1", "node_id": 22, "node_type": "control",
                                                             "sensors": ["tuf", "hnda"], "name": "Valve 22"})
    assert mon.status_code == 201 and ctl.status_code == 201, (mon.text, ctl.text)
    assert mon.json()["node_type"] == "monitoring" and mon.json()["sensors"] == ["hnda", "sondas"]
    bad = supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Region_1", "node_id": 23, "node_type": "control", "sensors": ["laser"]})
    assert bad.status_code == 400 and "laser" in bad.json()["detail"]
    # legacy kind still maps onto the two types
    legacy = supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Region_1", "node_id": 24, "kind": "valve"})
    assert legacy.json()["node_type"] == "control"
    # CSV round-trip with type + sensors
    res = supervisor.post(f"{API}/org/nodes/import", params=q, json={"csv": "region,node_id,name,type,sensors\nRegion_1,25,Flow 25,monitoring,supmea|tuf\n"}).json()
    assert res["created"] == 1 and not res["errors"]
    csv_text = supervisor.get(f"{API}/org/nodes/export.csv", params=q).text
    assert "Region_1,25,Flow 25,monitoring,supmea|tuf" in csv_text
    # fleet carries the type; discovered nodes carry the sensors detected from sensor_mask
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/21/status", _status(21))
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/30/status", _status(30))  # sensor_mask=3 -> tuf + hnda
    fleet = {n["node_id"]: n for n in supervisor.get(f"{API}/fleet", params=q).json()["nodes"]}
    assert fleet[21]["node_type"] == "monitoring" and fleet[21]["sensors"] == ["hnda", "sondas"]
    disc = {d["node_id"]: d for d in supervisor.get(f"{API}/org/nodes", params=q).json()["discovered"]}
    assert disc[30]["sensors_detected"] == ["tuf", "hnda"]


def test_valve_commands_need_a_control_node(supervisor, app):
    q = {"company": "Company_1"}
    supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Region_1", "node_id": 41, "node_type": "monitoring"})
    supervisor.post(f"{API}/org/nodes", params=q, json={"region": "Region_1", "node_id": 42, "node_type": "control"})
    body = {"company": "Company_1", "region": "Region_1", "cmd_type": "VALVE", "cmd_data": 1, "delivery": "next_wake"}
    refused = supervisor.post(f"{API}/commands", json={**body, "node_id": 41})
    assert refused.status_code == 409 and "monitoring node" in refused.json()["detail"]
    assert supervisor.post(f"{API}/commands", json={**body, "node_id": 42}).status_code == 202
    assert supervisor.post(f"{API}/commands", json={**body, "node_id": 43}).status_code == 202  # unregistered: unchanged
    # non-actuation commands still reach monitoring nodes
    assert supervisor.post(f"{API}/commands", json={**body, "node_id": 41, "cmd_type": "STRAN", "cmd_data": 60}).status_code == 202


def test_farm_respects_monitoring_nodes(supervisor, app):
    import json as _json
    from wiot.config import PACKAGE_DIR
    from wiot.services.farm import FarmLayout
    rt = app.state.runtime
    layout = _json.loads((PACKAGE_DIR / "data" / "demo_farm_layout.json").read_text(encoding="utf-8"))
    layout["zones"] = layout["zones"][:2]
    layout["devices"] = layout["devices"][:2]
    rt.farm.store.put("Company_1", FarmLayout.model_validate(layout), "test")
    supervisor.post(f"{API}/org/nodes", params={"company": "Company_1"}, json={"region": "Region_1", "node_id": 1, "node_type": "monitoring"})
    zone = layout["zones"][0]["id"]
    r = supervisor.patch(f"{API}/farm/zones/{zone}", params={"company": "Company_1"}, json={"auto_irrigation": True})
    assert r.status_code == 400 and "monitoring node" in r.json()["detail"]
    o = supervisor.get(f"{API}/farm/overview", params={"company": "Company_1"}).json()
    types = {z["node_id"]: z["node_type"] for z in o["zones"]}
    assert types[1] == "monitoring" and types[2] is None
