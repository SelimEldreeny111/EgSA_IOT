"""Release 2.6: phone app and push alerts, commissioning, maintenance and the optional assistant (24-26, 31)."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from wiot.protocol import messages_pb2 as pb
from wiot.services.commissioning import parse_qr
from wiot.services.push import b64u, decrypt, encrypt

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 100


def browser_keys():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, b64u(pub), b64u(b"0123456789abcdef")


def status(node=5, battery=3.9, rtc=True, mask=2) -> bytes:
    return pb.Status_Message(node_id=node, sensor_id=1, timestamp=int(time.time()), battery_voltage=battery, sensor_mask=mask,
                             active_sensor_count=1, rtc_valid=rtc, sample_time_valid=rtc, soil_moisture=24.0,
                             soil_moisture_temp_valid=1, power_mode=2).SerializeToString()


# ------------------------------------------------------------------ point 24
def test_web_push_encryption_roundtrip_rfc8291():
    key, p256dh, auth = browser_keys()
    body = encrypt(b'{"title":"hi"}', p256dh, auth)
    assert int.from_bytes(body[16:20], "big") == 4096 and body[20] == 65
    assert decrypt(body, key, auth) == b'{"title":"hi"}'


def test_push_subscription_vapid_and_alert_delivery(supervisor):
    rt = supervisor.app.state.runtime
    key, p256dh, auth = browser_keys()
    endpoint = "https://push.example.com/send/abc123"
    assert supervisor.post("/api/v2/push/subscribe", json={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}).status_code == 201
    assert supervisor.post("/api/v2/push/subscribe", json={"endpoint": "http://x", "keys": {"p256dh": p256dh, "auth": auth}}).status_code == 400
    calls = []

    def http(method, url, headers, body, timeout=10):
        calls.append((url, headers, body))
        return 201, ""
    rt.push.http = http
    rt.push.on_event("alert", {"alert_kind": "low_battery", "kind": "low_battery", "severity": "warning", "state": "open",
                               "node_id": 2, "region": "Region_1", "alert_id": 7, "details": {"battery_v": 3.2}}, "Company_1")
    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    url, headers, body = calls[0]
    assert url == endpoint and headers["Content-Encoding"] == "aes128gcm"
    token = headers["Authorization"].split("t=")[1].split(",")[0]
    pub = serialization.load_der_public_key(rt.push.key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
    assert jwt.decode(token, pub, algorithms=["ES256"], audience="https://push.example.com")["sub"]
    payload = json.loads(decrypt(body, key, auth))
    assert payload["title"].startswith("Warning: Low battery") and payload["url"] == "/#/alerts"
    rt.push.on_event("alert", {"severity": "info", "state": "open"}, "Company_1")          # info alerts are not pushed
    rt.push.http = lambda *a, **k: (410, "")
    with rt.main.connect() as db:
        sub = dict(db.execute("SELECT * FROM push_subscriptions").fetchone())
    assert rt.push.send(sub, {"title": "x"}) == 410
    assert rt.push.count(sub["user_id"]) == 0                                              # gone subscriptions are removed


def test_pwa_files_are_served(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["display"] == "standalone"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["service-worker-allowed"] == "/"
    assert "arcgisonline" in sw.headers["content-security-policy"]                         # tiles may be cached offline
    assert "camera=(self)" in client.get("/login").headers["permissions-policy"]


# ------------------------------------------------------------------ point 25
def test_qr_label_formats():
    assert parse_qr("12") == {"node_id": 12}
    q = parse_qr("WIOT:Company_1/Region_1/12?type=control&sensors=tuf,hnda,xyz&name=P-12")
    assert q == {"company": "Company_1", "region": "Region_1", "node_id": 12, "type": "control", "sensors": ["tuf", "hnda"], "name": "P-12"}
    assert parse_qr('{"node_id": 9, "type": "monitoring"}')["node_id"] == 9
    with pytest.raises(ValueError):
        parse_qr("https://evil.example.com")


def test_commissioning_flow(supervisor):
    rt = supervisor.app.state.runtime
    r = supervisor.post("/api/v2/commission/register", params={"company": "Company_1"},
                        json={"node_id": 5, "region": "Region_1", "name": "P-12 probe", "type": "monitoring", "sensors": ["hnda"],
                              "lat": 22.25, "lon": 28.72})
    assert r.status_code == 200, r.text
    c = supervisor.get("/api/v2/commission/check", params={"company": "Company_1", "node_id": 5}).json()
    assert c["ready"] is False and next(i for i in c["items"] if i["key"] == "uplink")["ok"] is False
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/5/status", status(rtc=False))
    c = supervisor.get("/api/v2/commission/check", params={"company": "Company_1", "node_id": 5}).json()
    clock = next(i for i in c["items"] if i["key"] == "clock")
    assert c["ready"] is True and clock["ok"] is False and clock["blocking"] is False
    assert supervisor.post("/api/v2/commission/clock", params={"company": "Company_1", "node_id": 5}).json()["request_id"]
    pdf = supervisor.post("/api/v2/commission/complete", params={"company": "Company_1", "format": "pdf"},
                          json={"node_id": 5, "region": "Region_1", "notes": "Installed at the pivot centre"})
    assert pdf.content.startswith(b"%PDF") and b"NODE-005" in pdf.content
    assets = supervisor.get("/api/v2/maintenance/assets", params={"company": "Company_1"}).json()["assets"]
    asset = next(a for a in assets if a["node_id"] == 5)
    recs = supervisor.get("/api/v2/maintenance/records", params={"company": "Company_1", "asset_id": asset["id"]}).json()["records"]
    assert recs[0]["kind"] == "commissioning"


def test_commissioning_blocks_a_low_battery(supervisor):
    rt = supervisor.app.state.runtime
    supervisor.post("/api/v2/commission/register", params={"company": "Company_1"}, json={"node_id": 6, "sensors": ["hnda"]})
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/6/status", status(node=6, battery=3.3))
    c = supervisor.get("/api/v2/commission/check", params={"company": "Company_1", "node_id": 6}).json()
    assert c["ready"] is False and next(i for i in c["items"] if i["key"] == "battery")["ok"] is False
    assert supervisor.post("/api/v2/commission/complete", params={"company": "Company_1"}, json={"node_id": 6}).status_code == 400


# ------------------------------------------------------------------ point 26
def test_work_order_lifecycle_with_photo(supervisor):
    o = supervisor.post("/api/v2/maintenance/orders", params={"company": "Company_1"}, json={
        "title": "Replace soil probe", "node_id": 2, "priority": "high", "alert_id": 3, "due": "2026-12-01"}).json()
    assert o["status"] == "open" and o["asset"] == "NODE-002"
    p = supervisor.post(f"/api/v2/maintenance/orders/{o['id']}/photos", params={"company": "Company_1", "caption": "before"},
                        content=PNG, headers={"Content-Type": "image/png"})
    assert p.status_code == 201, p.text
    assert supervisor.post(f"/api/v2/maintenance/orders/{o['id']}/photos", params={"company": "Company_1"},
                           content=b"GIF89a", headers={"Content-Type": "image/gif"}).status_code == 400
    img = supervisor.get(f"/api/v2/maintenance/photos/{p.json()['photo']}", params={"company": "Company_1"})
    assert img.status_code == 200 and img.content == PNG
    assert supervisor.patch(f"/api/v2/maintenance/orders/{o['id']}", params={"company": "Company_1"},
                            json={"status": "done"}).status_code == 400                    # closure note required
    done = supervisor.patch(f"/api/v2/maintenance/orders/{o['id']}", params={"company": "Company_1"},
                            json={"status": "done", "closure": "Probe replaced, readings valid"}).json()
    assert done["status"] == "done" and done["closed_at"] and [e["kind"] for e in done["events"]] == ["created", "photo", "status"]
    assert supervisor.get("/api/v2/maintenance/orders", params={"company": "Company_1", "status": "active"}).json()["orders"] == []


def test_calibration_history_and_overdue_alert(supervisor):
    rt = supervisor.app.state.runtime
    a = supervisor.post("/api/v2/maintenance/assets", params={"company": "Company_1"},
                        json={"name": "Main line meter", "kind": "flow_meter", "serial": "TUF-1234"}).json()
    c = supervisor.post(f"/api/v2/maintenance/assets/{a['id']}/calibrations", params={"company": "Company_1"},
                        json={"date": "2025-01-10", "reference": 100.0, "measured": 103.0, "unit": "m3", "tolerance_pct": 2,
                              "next_due": "2026-01-10"}).json()
    assert c["deviation_pct"] == 3.0 and c["pass"] is False
    fired = rt.maint.check_alerts(rt.alerts, "Company_1", int(time.time()))
    assert fired and fired[0]["alert_kind"] == f"calibration_due_{a['id']}"


# ------------------------------------------------------------------ point 31
def block(**kw):
    return SimpleNamespace(**kw)


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


def fake_client(script):
    msgs = FakeMessages(script)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_assistant_answers_with_read_only_tools(supervisor):
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/5/status", status())
    client, msgs = fake_client([
        SimpleNamespace(stop_reason="tool_use", usage=SimpleNamespace(input_tokens=100, output_tokens=20), content=[
            block(type="thinking", thinking=""), block(type="tool_use", id="t1", name="get_fleet_status", input={"region": "Region_1"}),
            block(type="tool_use", id="t2", name="send_command", input={})]),
        SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=300, output_tokens=40),
                        content=[block(type="text", text="NODE-005 is online with 3.90 V.")]),
    ])
    rt.settings.assistant_enabled = True
    rt.assistant.client_factory = lambda: client
    r = supervisor.post("/api/v2/assistant/ask", params={"company": "Company_1"}, json={"question": "How is NODE-005?"})
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "NODE-005 is online with 3.90 V." and r.json()["tools"] == ["get_fleet_status", "send_command"]
    first = msgs.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default" and "tool_choice" not in first
    assert {t["name"] for t in first["tools"]} == {"get_fleet_status", "get_open_alerts", "get_node_health", "get_farm_overview", "get_water_use"}
    results = msgs.calls[1]["messages"][2]["content"]                    # user turn with the tool results
    fleet = json.loads(results[0]["content"])
    assert fleet["nodes"][0]["node_id"] == 5 and "Company_2" not in results[0]["content"]
    assert results[1]["is_error"] is True                                     # no write tools exist
    hist = supervisor.get("/api/v2/assistant", params={"company": "Company_1"}).json()
    assert hist["ready"] and hist["history"][0]["question"] == "How is NODE-005?"
    actions = [a["action"] for a in rt.main.list_audit("Company_1")]
    assert "assistant_question" in actions


def test_assistant_refusal_rate_limit_and_off_switch(supervisor):
    rt = supervisor.app.state.runtime
    assert supervisor.post("/api/v2/assistant/ask", json={"question": "hi"}).status_code == 409   # off by default
    client, _ = fake_client([SimpleNamespace(stop_reason="refusal", usage=None, content=[])])
    rt.settings.assistant_enabled, rt.settings.assistant_max_per_hour = True, 1
    rt.assistant.client_factory = lambda: client
    r = supervisor.post("/api/v2/assistant/ask", json={"question": "hi"})
    assert r.json()["answer"] == "The assistant declined to answer this question."
    assert supervisor.post("/api/v2/assistant/ask", json={"question": "again"}).status_code == 403
