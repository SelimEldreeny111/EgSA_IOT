"""Track G: third-party devices (point 53) and the greenhouse layout editor (point 58)."""
from __future__ import annotations

import json
import time

import pytest

from tests.conftest import PASSWORDS, login
from wiot.domain.ext_metrics import (apply_mapping, auto_mapping, check_mapping, flatten, mqtt_signature, parse_time,
                                     verify_signature)

API = "/api/v2"
Q = {"company": "Company_1"}
LAT, LON = 30.0500, 31.2300


def _rt(client):
    return client.app.state.runtime


def _signed(topic: str, secret: str, inner: dict) -> bytes:
    p = json.dumps(inner)
    return json.dumps({"p": p, "sig": mqtt_signature(secret, topic, p)}).encode()


def _device(client, **extra) -> dict:
    body = {"device_id": "GH1-CLIMATE", "name": "House 1 climate", "protocol": "mqtt", "interval_s": 300, **extra}
    r = client.post(f"{API}/devices", params=Q, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _rect(lat, lon, dlat, dlon):
    return [[lat, lon], [lat, lon + dlon], [lat + dlat, lon + dlon], [lat + dlat, lon]]


# ------------------------------------------------------------- pure helpers
def test_mapping_and_payload_helpers():
    fields = flatten({"temperature": 24.5, "humidity": "61", "co2": 812, "ok": True, "climate": {"par": 410},
                      "name": "x", "bad": float("inf")})
    assert fields == {"temperature": 24.5, "humidity": 61.0, "co2": 812.0, "climate.par": 410.0}
    auto = {m["field"]: m["metric"] for m in auto_mapping(fields)}
    assert auto == {"temperature": "air_temp_c", "humidity": "air_rh_pct", "co2": "co2_ppm", "climate.par": "par_umol"}
    values, rejected = apply_mapping({"t": 2450, "rh": 140}, check_mapping(
        [{"field": "t", "metric": "air_temp_c", "scale": 0.01}, {"field": "rh", "metric": "air_rh_pct"}]))
    assert values == {"air_temp_c": 24.5} and rejected[0]["metric"] == "air_rh_pct"
    for bad in ([{"field": "a b", "metric": "co2_ppm"}], [{"field": "a", "metric": "nope"}],
                [{"field": "a", "metric": "co2_ppm", "scale": 0}], [{"field": "a", "metric": "co2_ppm"}] * 2):
        with pytest.raises(ValueError):
            check_mapping(bad)
    assert parse_time("2026-11-17T08:30:00.123456789Z") == parse_time("2026-11-17T08:30:00Z")
    assert parse_time(1763368200000) == 1763368200 and parse_time(True) is None
    sig = mqtt_signature("s3cret", "wiotx/C/d/up", '{"ts":1}')
    assert verify_signature("s3cret", "wiotx/C/d/up", '{"ts":1}', sig)
    assert not verify_signature("s3cret", "wiotx/C/other/up", '{"ts":1}', sig)       # topic is bound
    assert not verify_signature("s3cret", "wiotx/C/d/up", '{"ts":2}', sig)


# ------------------------------------------------------------ registry + MQTT
def test_signed_mqtt_device_secret_once_replay_refused(supervisor):
    rt = _rt(supervisor)
    created = _device(supervisor)
    secret = created["secret"]
    assert secret and created["topic"] == "wiotx/Company_1/GH1-CLIMATE/up" and created["secret_set"]
    listed = supervisor.get(f"{API}/devices", params=Q).json()
    assert "secret" not in json.dumps(listed["devices"]) .replace('"secret_set"', "")
    events = []
    rt.hub.listeners.append(lambda e, d, c: events.append((e, d, c)) if e == "device_reading" else None)
    topic, now = created["topic"], int(time.time())
    good = _signed(topic, secret, {"ts": now - 60, "temperature": 24.5, "humidity": 61, "co2": 812})
    rt.devices.on_mqtt(topic, good)
    rt.devices.on_mqtt(topic, good)                                                  # replay of the same message
    rt.devices.on_mqtt(topic, _signed(topic, secret, {"ts": now - 120, "co2": 900}))  # older than the last one
    rt.devices.on_mqtt(topic, _signed(topic, "wrong-secret", {"ts": now, "co2": 900}))
    rt.devices.on_mqtt(topic, json.dumps({"ts": now, "co2": 900}).encode())           # unsigned to a signed device
    dev = supervisor.get(f"{API}/devices", params=Q).json()["devices"][0]
    assert dev["values"]["co2_ppm"]["value"] == 812 and dev["values"]["co2_ppm"]["trusted"] is True
    assert dev["stats"]["accepted"] == 1 and dev["stats"]["rejected"] == 4 and dev["state"] == "online"
    assert [e[1]["values"]["co2_ppm"] for e in events] == [812] and events[0][2] == "Company_1"
    series = supervisor.get(f"{API}/devices/GH1-CLIMATE/series", params={**Q, "metric": "air_temp_c"}).json()
    assert series["resolution"] == "raw" and series["points"] == [[now - 60, 24.5]]
    # after a restart the replay guard comes from the stored readings
    from wiot.services.devices import DeviceService
    fresh = DeviceService(rt.main, rt.telemetry, rt.hub, rt.logs, rt.settings.secret_key.get_secret_value(),
                          rt.main.company_names)
    fresh.on_mqtt(topic, _signed(topic, secret, {"ts": now - 300, "co2": 999}))
    assert fresh.stats[("Company_1", "GH1-CLIMATE")]["rejected"] == 1
    # rotating the secret invalidates the old one
    new = supervisor.post(f"{API}/devices/GH1-CLIMATE/secret", params=Q).json()["secret"]
    rt.devices.on_mqtt(topic, _signed(topic, secret, {"ts": now, "co2": 700}))
    rt.devices.on_mqtt(topic, _signed(topic, new, {"ts": now, "co2": 700}))
    dev = supervisor.get(f"{API}/devices", params=Q).json()["devices"][0]
    assert dev["values"]["co2_ppm"]["value"] == 700


def test_unsigned_device_mapping_unknown_and_validation(supervisor):
    rt = _rt(supervisor)
    _device(supervisor, device_id="TANK-1", name="Tank 1", auth="none",
            mapping=[{"field": "lvl", "metric": "level_pct"}, {"field": "d.mm", "metric": "distance_mm", "scale": 1}])
    topic = "wiotx/Company_1/TANK-1/up"
    rt.devices.on_mqtt(topic, json.dumps({"lvl": 63.5, "d": {"mm": 1200}, "temperature": 30}).encode())
    rt.devices.on_mqtt(topic, json.dumps({"lvl": 250}).encode())                      # out of range: rejected
    rt.devices.on_mqtt("wiotx/Company_1/NOT-REGISTERED/up", b'{"co2": 1}')
    rt.devices.on_mqtt("wiotx/Nobody/x/up", b'{"co2": 1}')
    body = supervisor.get(f"{API}/devices", params=Q).json()
    tank = next(d for d in body["devices"] if d["device_id"] == "TANK-1")
    assert tank["values"]["level_pct"]["value"] == 63.5 and tank["values"]["level_pct"]["trusted"] is False
    assert "air_temp_c" not in tank["values"]                                         # explicit mapping only
    assert tank["last_payload"]["rejected"][0]["metric"] == "level_pct"
    assert [u["id"] for u in body["unknown"]] == ["NOT-REGISTERED"]
    assert rt.devices.dropped["unknown_company"] == 1
    for bad in ({"device_id": "x y", "name": "a"}, {"device_id": "LW", "name": "a", "protocol": "lorawan"},
                {"device_id": "catalog", "name": "a"}, {"device_id": "TANK-1", "name": "dup"},
                {"device_id": "M", "name": "a", "mapping": [{"field": "a", "metric": "nope"}]}):
        assert supervisor.post(f"{API}/devices", params=Q, json=bad).status_code == 400, bad
    # API tokens may not create devices (secrets), read-only users may not either
    token = supervisor.post(f"{API}/org/tokens", params=Q, json={"name": "erp", "scope": "write"}).json()["token"]
    from fastapi.testclient import TestClient
    machine = TestClient(supervisor.app)
    assert machine.post(f"{API}/devices", params=Q, json={"device_id": "Z", "name": "z"},
                        headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert machine.get(f"{API}/devices", params=Q, headers={"Authorization": f"Bearer {token}"}).status_code == 200
    r = supervisor.delete(f"{API}/devices/TANK-1", params=Q).json()
    assert r["readings_deleted"] == 2                                                # level + distance rows
    assert supervisor.get(f"{API}/devices/TANK-1/series", params={**Q, "metric": "level_pct"}).status_code == 404


# ---------------------------------------------------------------- LoRaWAN
def _ttn(eui, decoded, rssi=-97.0):
    return {"end_device_ids": {"device_id": "eui-x", "dev_eui": eui},
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%S.123456789Z", time.gmtime()),
            "uplink_message": {"f_cnt": 7, "decoded_payload": decoded,
                               "rx_metadata": [{"rssi": rssi - 10, "snr": 1.0}, {"rssi": rssi, "snr": 7.5}]}}


def test_ttn_and_chirpstack_webhooks(supervisor):
    _device(supervisor, device_id="SOIL-7", name="Bed 7 soil", protocol="lorawan", dev_eui="a8:40:41:00:00:00:00:07")
    ttn = supervisor.post(f"{API}/devices/sources", params=Q, json={"name": "TTN app", "kind": "ttn"}).json()
    cs = supervisor.post(f"{API}/devices/sources", params=Q, json={"name": "ChirpStack", "kind": "chirpstack"}).json()
    assert ttn["key"].startswith("wiotsrc_") and not ttn["key"].startswith("wiot_")
    assert "key" not in supervisor.get(f"{API}/devices/sources", params=Q).json()["sources"][0]
    from fastapi.testclient import TestClient
    ns = TestClient(supervisor.app)                       # the network server: no session, no CSRF
    auth = {"Authorization": f"Bearer {ttn['key']}"}
    r = ns.post(f"{API}/ingest/ttn", headers=auth, json=_ttn("A840410000000007", {"soil_moisture": 31.5, "temp_soil": 22.1}))
    assert r.status_code == 202 and r.json()["accepted"] and r.json()["stored"] == 4, r.text
    assert ns.post(f"{API}/ingest/ttn", headers=auth, json=_ttn("A840410000000099", {"x": 1})).json()["accepted"] is False
    assert ns.post(f"{API}/ingest/ttn", headers=auth, json={"end_device_ids": {}, "join_accept": {}}).json()["accepted"] is False
    assert ns.post(f"{API}/ingest/ttn", json=_ttn("A840410000000007", {})).status_code == 401
    assert ns.post(f"{API}/ingest/ttn", headers={"X-WIOT-Key": cs["key"]}, json={}).status_code == 403
    assert ns.post(f"{API}/ingest/ttn", headers={**auth, "Content-Type": "text/plain"}, content=b"x").status_code == 415
    cs_auth = {"X-WIOT-Key": cs["key"]}
    up = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 5)),
          "deviceInfo": {"devEui": "a840410000000007", "deviceName": "bed7"}, "object": {"soil": {"soil_ec": 1.8}},
          "rxInfo": [{"rssi": -80, "snr": 9}]}
    assert ns.post(f"{API}/ingest/chirpstack", params={"event": "up"}, headers=cs_auth, json=up).json()["stored"] == 3
    status = {"deviceInfo": {"devEui": "A840410000000007"}, "batteryLevel": 82.5}
    assert ns.post(f"{API}/ingest/chirpstack", params={"event": "status"}, headers=cs_auth, json=status).json()["stored"] == 1
    assert ns.post(f"{API}/ingest/chirpstack", params={"event": "join"}, headers=cs_auth, json=up).json()["accepted"] is False
    body = supervisor.get(f"{API}/devices", params=Q).json()
    vals = body["devices"][0]["values"]
    assert vals["soil_moisture_pct"]["value"] == 31.5 and vals["rssi_dbm"]["value"] == -80 and vals["snr_db"]["value"] == 9
    assert vals["soil_ec_ds_m"]["value"] == 1.8 and vals["battery_pct"]["value"] == 82.5
    assert [u["id"] for u in body["unknown"]] == ["A840410000000099"]
    supervisor.delete(f"{API}/devices/sources/{ttn['id']}", params=Q)
    assert ns.post(f"{API}/ingest/ttn", headers=auth, json=_ttn("A840410000000007", {})).status_code == 401
    # a DevEUI belongs to one device per company
    assert supervisor.post(f"{API}/devices", params=Q, json={"device_id": "DUP", "name": "d", "protocol": "lorawan",
                                                             "dev_eui": "A840410000000007"}).status_code == 400


# ------------------------------------------------------------ alerts + retention
def test_silent_device_alert_and_retention(supervisor):
    rt = _rt(supervisor)
    _device(supervisor, auth="none")
    now = int(time.time())
    rt.devices.store.save("Company_1", "GH1-CLIMATE", now - 4000, now - 4000, {"co2_ppm": 600}, False, "mqtt")
    fired = rt.alerts.check(now)
    silent = [f for f in fired if f["alert_kind"] == "device_silent_GH1-CLIMATE"]
    assert silent and silent[0]["severity"] == "warning" and silent[0]["details"]["name"] == "House 1 climate"
    from wiot.services.notify import alert_text
    subject, body = alert_text("Company_1", silent[0])
    assert "Device silent: House 1 climate" in subject and "DEVICE GH1-CLIMATE" in body
    rt.devices.on_mqtt("wiotx/Company_1/GH1-CLIMATE/up", b'{"co2": 640}')
    assert [f["kind"] for f in rt.alerts.check(now + 5) if f["alert_kind"] == "device_silent_GH1-CLIMATE"] == \
        ["device_silent_GH1-CLIMATE_resolved"]
    old = now - 400 * 86400
    rt.devices.store.save("Company_1", "GH1-CLIMATE", old, old, {"co2_ppm": 500}, False, "mqtt")
    assert rt.devices.retention("Company_1", 30, now) == 1                   # minimum retention is 365 days
    long = supervisor.get(f"{API}/devices/GH1-CLIMATE/series",
                          params={**Q, "metric": "co2_ppm", "hours": 24 * 399}).json()
    assert long["resolution"] == "hourly" and len(long["points"]) >= 2      # hourly summary outlives raw rows


def test_json_topics_bypass_aes_framing():
    from wiot.protocol.topics import SUBSCRIPTIONS
    from wiot.protocol.transport import MqttNodeClient
    assert "wiotx/+/+/up" in SUBSCRIPTIONS
    got, plain = [], []
    client = MqttNodeClient("localhost", 1883, bytes(16), "t", list(SUBSCRIPTIONS), on_plaintext=lambda *a: plain.append(a),
                            on_json=lambda t, p: got.append((t, p)), json_root="wiotx")
    client.is_connected = lambda: True

    class Msg:
        topic, payload = "wiotx/Company_1/D1/up", b'{"co2": 1}'
    client._on_message(None, None, Msg)
    assert got == [("wiotx/Company_1/D1/up", b'{"co2": 1}')] and plain == []


# ------------------------------------------------------------------ greenhouses
def _layout(bench_offset=0.0, attach=None, benches=None):
    return {"houses": [{
        "id": "GH-1", "name": "Tomato house", "kind": "glass", "polygon": _rect(LAT, LON, 0.0005, 0.0008),
        "zones": [{"id": "GH-1-A", "name": "Zone A", "crop": "Tomato", "polygon": _rect(LAT + 0.00005, LON + 0.00005, 0.0002, 0.0007),
                   "attach": attach or [],
                   "benches": benches if benches is not None else
                   [{"id": "B-1", "name": "Bench 1", "polygon": _rect(LAT + 0.0001 + bench_offset, LON + 0.0001, 0.00003, 0.0005)}]}]}]}


def test_greenhouse_layout_versions_warnings_live(supervisor):
    rt = _rt(supervisor)
    empty = supervisor.get(f"{API}/greenhouses/layout", params=Q).json()
    assert empty["version"] == 0 and empty["layout"] == {"houses": []} and empty["can_edit"] and "center" in empty["view"]
    _device(supervisor, auth="none")
    attach = [{"kind": "device", "device_id": "GH1-CLIMATE"}, {"kind": "node", "region": "Region_1", "node_id": 3}]
    r = supervisor.put(f"{API}/greenhouses/layout", params=Q, json={"version": 0, "layout": _layout(attach=attach)})
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["warnings"] == [], r.text
    s = r.json()["summary"]
    assert (s["houses"], s["zones"], s["benches"], s["attachments"]) == (1, 1, 1, 2) and 3000 < s["area_m2"] < 4500
    stale = supervisor.put(f"{API}/greenhouses/layout", params=Q, json={"version": 0, "layout": _layout()})
    assert stale.status_code == 409
    out = supervisor.put(f"{API}/greenhouses/layout", params=Q, json={"version": 1, "layout": _layout(bench_offset=0.001)})
    assert out.json()["warnings"] == ["Bench B-1 extends outside GH-1-A"]
    dup = _layout()
    dup["houses"][0]["zones"][0]["benches"][0]["id"] = "GH-1"
    assert supervisor.put(f"{API}/greenhouses/layout", params=Q, json={"version": 2, "layout": dup}).status_code == 422
    flat = _layout()
    flat["houses"][0]["polygon"] = [[LAT, LON], [LAT, LON + 0.001], [LAT, LON + 0.002]]
    assert supervisor.put(f"{API}/greenhouses/layout", params=Q, json={"version": 2, "layout": flat}).status_code == 422
    supervisor.put(f"{API}/greenhouses/layout", params=Q, json={"version": 2, "layout": _layout(attach=attach)})
    rt.devices.on_mqtt("wiotx/Company_1/GH1-CLIMATE/up", b'{"temperature": 26.0, "co2": 900, "batv": 3.6}')
    live = supervisor.get(f"{API}/greenhouses/live", params=Q).json()["values"]
    assert live["GH-1"]["air_temp_c"]["value"] == 26.0 and live["GH-1-A"]["co2_ppm"]["n"] == 1
    assert "battery_v" not in live["GH-1"] and "B-1" not in live                # device health stays off the map
    dev = supervisor.get(f"{API}/devices", params=Q).json()["devices"][0]
    assert dev["locations"] == ["Tomato house › Zone A"]
    att = supervisor.get(f"{API}/greenhouses/attachables", params=Q).json()
    assert att["devices"][0]["device_id"] == "GH1-CLIMATE"


def test_greenhouse_large_layout_and_permissions(supervisor):
    benches = [{"id": f"B-{i}", "name": f"Bench {i}", "polygon": _rect(LAT + 0.00006 + i * 0.0000002, LON + 0.0001, 0.0000001, 0.0005)}
               for i in range(900)]
    body = {"version": 0, "layout": _layout(benches=benches)}
    assert len(json.dumps(body)) > 64 * 1024
    r = supervisor.put(f"{API}/greenhouses/layout", params=Q, json=body)
    assert r.status_code == 200 and r.json()["summary"]["benches"] == 900, r.text[:300]
    from fastapi.testclient import TestClient
    mon = TestClient(supervisor.app)
    mon.headers["X-CSRF-Token"] = login(mon, "Super_User", PASSWORDS["WIOT_MONITOR_PASSWORD"])
    got = mon.get(f"{API}/greenhouses/layout", params=Q).json()
    assert got["can_edit"] is False and got["summary"]["benches"] == 900
    assert mon.put(f"{API}/greenhouses/layout", params=Q, json={"version": 1, "layout": _layout()}).status_code == 403
    assert mon.post(f"{API}/devices", params=Q, json={"device_id": "Z", "name": "z"}).status_code == 403
    rt = _rt(supervisor)
    rt.security.set_pages(rt.main.get_user("Super_User")["id"], ["devices", "greenhouses"])


def test_demo_seed_and_simulated_devices(supervisor):
    """Demo_AgriFarm gets two greenhouses and four unsigned devices; the simulator's JSON maps onto them."""
    rt = _rt(supervisor)
    assert supervisor.post(f"{API}/org/companies", json={"name": "Demo_AgriFarm"}).status_code == 201
    names = rt.main.company_names()
    assert rt.devices.seed_demo(names) and rt.greenhouses.seed_demo(names)
    assert not rt.devices.seed_demo(names) and not rt.greenhouses.seed_demo(names)      # only once
    from wiot.sim.fleet import ext_devices
    sims = ext_devices(names, 5, 7)
    assert {d.device_id for d in sims} == {d["device_id"] for d in rt.devices.store.list("Demo_AgriFarm")}
    for dev in sims:
        rt.devices.on_mqtt(dev.topic, json.dumps(dev.payload(time.time())).encode())
    got = supervisor.get(f"{API}/devices", params={"company": "Demo_AgriFarm"}).json()["devices"]
    assert all(d["state"] == "online" and d["values"] for d in got)
    sub = next(d for d in got if d["device_id"] == "GH1-SUBSTRATE")["values"]
    assert 1.5 < sub["soil_ec_ds_m"]["value"] < 3.5                                   # µS/cm scaled by 0.001
    layout = supervisor.get(f"{API}/greenhouses/layout", params={"company": "Demo_AgriFarm"}).json()
    assert layout["summary"]["houses"] == 2 and layout["warnings"] == []
    live = supervisor.get(f"{API}/greenhouses/live", params={"company": "Demo_AgriFarm"}).json()["values"]
    assert "air_temp_c" in live["GH-1"] and "soil_ec_ds_m" in live["GH-1-A"]


# ------------------------------------------------------------ review fixes
def test_public_broker_abuse_does_not_block_or_break(supervisor):
    """Junk on a signed device's topic cannot use up its allowance; hostile keys cannot break the page."""
    rt = _rt(supervisor)
    secret = _device(supervisor)["secret"]
    topic = "wiotx/Company_1/GH1-CLIMATE/up"
    for _ in range(80):
        rt.devices.on_mqtt(topic, b"junk")
    rt.devices.on_mqtt(topic, _signed(topic, secret, {"ts": int(time.time()), "temperature": 21.5}))
    dev = supervisor.get(f"{API}/devices", params=Q).json()["devices"][0]
    assert dev["values"]["air_temp_c"]["value"] == 21.5
    rt.devices.on_mqtt("wiotx/Company_1/ghost/up", b'{"\ud800": 1, "co2": 5}')
    rt.devices.on_mqtt("wiotx/Company_1/ghost2/up", b'{"t": 1' + b"0" * 400 + b"}")            # too big for a float
    rt.devices.on_mqtt("wiotx/Company_1/ghost3/up", b"[" * 5000 + b"]" * 5000)                 # nesting bomb
    r = supervisor.get(f"{API}/devices", params=Q)
    assert r.status_code == 200 and "ghost" in [u["id"] for u in r.json()["unknown"]]
    from fastapi.testclient import TestClient
    ns = TestClient(supervisor.app)
    assert ns.post(f"{API}/ingest/ttn", content=b"[" * 5000, headers={"Content-Type": "application/json"}).status_code == 401
    key = supervisor.post(f"{API}/devices/sources", params=Q, json={"name": "t", "kind": "ttn"}).json()["key"]
    bad = ns.post(f"{API}/ingest/ttn", headers={"Authorization": f"Bearer {key}"},
                  json={"end_device_ids": "x", "uplink_message": {"decoded_payload": {"t": 10 ** 400}}})
    assert bad.status_code == 202 and bad.json()["accepted"] is False


def test_delete_resolves_alert_and_seed_is_one_shot(supervisor):
    rt = _rt(supervisor)
    _device(supervisor, auth="none")
    now = int(time.time())
    rt.devices.store.save("Company_1", "GH1-CLIMATE", now - 4000, now - 4000, {"co2_ppm": 600}, False, "mqtt")
    rt.alerts.check(now)
    events = []
    rt.hub.listeners.append(lambda e, d, c: events.append(d) if e == "alert" else None)
    supervisor.delete(f"{API}/devices/GH1-CLIMATE", params=Q)
    assert [e["kind"] for e in events] == ["device_silent_GH1-CLIMATE_resolved"]
    supervisor.post(f"{API}/org/companies", json={"name": "Demo_AgriFarm"})
    names = rt.main.company_names()
    assert rt.devices.seed_demo(names)
    for d in rt.devices.store.list("Demo_AgriFarm"):
        rt.devices.delete("Demo_AgriFarm", d["device_id"])
    assert not rt.devices.seed_demo(names) and rt.devices.store.list("Demo_AgriFarm") == []


def test_live_rollup_counts_each_sensor_once_and_flags_untrusted(supervisor):
    rt = _rt(supervisor)
    _device(supervisor, auth="none")
    attach = [{"kind": "device", "device_id": "GH1-CLIMATE"}]
    lay = _layout(attach=attach)
    lay["houses"][0]["attach"] = attach                                  # same sensor at house and zone level
    assert supervisor.put(f"{API}/greenhouses/layout", params=Q, json={"version": 0, "layout": lay}).status_code == 200
    rt.devices.on_mqtt("wiotx/Company_1/GH1-CLIMATE/up", json.dumps({"co2": 700, "ts": int(time.time()) + 500}).encode())
    live = supervisor.get(f"{API}/greenhouses/live", params=Q).json()["values"]["GH-1"]["co2_ppm"]
    assert live["n"] == 1 and live["untrusted"] == 1 and live["ts"] <= int(time.time())      # future stamp clamped
    cat = supervisor.get(f"{API}/devices/catalog", params=Q).json()
    assert cat["mqtt"]["public"] is True and cat["webhooks"]["public"] is False   # broker.hivemq.com; http test client
