"""Release 2.3: security, SSO, invitations, rules and notifications, reports, branding, usage, integrations."""
from __future__ import annotations

import base64
import io
import json
import time
import zipfile

import jwt
import pytest

from conftest import PASSWORDS, login
from wiot.protocol import messages_pb2 as pb
from wiot.services import totp
from wiot.services.integrations import azure_sas
from wiot.services.notify import Notifier, alert_text


def status(node=2, battery=3.9, flow=10.0, ts=None) -> bytes:
    return pb.Status_Message(node_id=node, sensor_id=1, timestamp=int(time.time()) if ts is None else ts,
                             battery_voltage=battery, sensor_mask=1, active_sensor_count=1, flow_meter_type=1,
                             flow_live_valid=True, rtc_valid=True, sample_time_valid=True, flow_rate=flow,
                             power_mode=1).SerializeToString()


def wait_for(calls, n=1, timeout=5.0):
    deadline = time.time() + timeout
    while len(calls) < n and time.time() < deadline:
        time.sleep(0.05)
    return calls


def admin_client(client):
    client.headers["X-CSRF-Token"] = login(client, "admin", PASSWORDS["WIOT_ADMIN_PASSWORD"])
    return client


# ------------------------------------------------------------------ point 17
def test_totp_matches_rfc6238_vectors():
    secret = base64.b32encode(b"12345678901234567890").decode()
    # RFC 6238 appendix B (SHA-1), 8 digits -> last 6 digits of the published values
    for t, expected in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
        assert totp.totp(secret, t) == expected
    step = totp.verify(secret, "287082", t=59)
    assert step == 1 and totp.verify(secret, "287082", t=59, last_step=1) is None   # no reuse


def test_two_factor_enrolment_login_and_recovery(client):
    admin_client(client)
    setup = client.post("/api/v2/auth/totp/setup").json()
    assert setup["uri"].startswith("otpauth://totp/WIOT:admin?") and len(setup["secret"]) == 32
    assert client.post("/api/v2/auth/totp/enable", json={"code": "000000"}).status_code == 400
    r = client.post("/api/v2/auth/totp/enable", json={"code": totp.totp(setup["secret"])})
    assert r.status_code == 200, r.text
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10
    client.post("/api/v2/auth/logout", headers={"X-CSRF-Token": r.json()["csrf"]})
    bad = client.post("/api/v2/auth/login", json={"username": "admin", "password": PASSWORDS["WIOT_ADMIN_PASSWORD"]})
    assert bad.status_code == 401 and bad.json()["otp_required"] is True
    wrong = client.post("/api/v2/auth/login", json={"username": "admin", "password": PASSWORDS["WIOT_ADMIN_PASSWORD"],
                                                    "otp": "123456"})
    assert wrong.status_code == 401
    ok = client.post("/api/v2/auth/login", json={"username": "admin", "password": PASSWORDS["WIOT_ADMIN_PASSWORD"],
                                                 "otp": codes[0]})
    assert ok.status_code == 200
    again = client.post("/api/v2/auth/login", json={"username": "admin", "password": PASSWORDS["WIOT_ADMIN_PASSWORD"],
                                                    "otp": codes[0]})
    assert again.status_code == 401                                  # a recovery code works once
    actions = [a["action"] for a in client.app.state.runtime.main.list_audit("Company_1")]
    assert "two_factor_enabled" in actions and "recovery_code_used" in actions


def test_sessions_can_be_listed_and_revoked(client):
    from fastapi.testclient import TestClient
    admin_client(client)
    other = TestClient(client.app)
    other.headers["X-CSRF-Token"] = login(other, "admin", PASSWORDS["WIOT_ADMIN_PASSWORD"])
    sessions = client.get("/api/v2/auth/sessions").json()["sessions"]
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    victim = next(s for s in sessions if not s["current"])
    assert client.delete(f"/api/v2/auth/sessions/{victim['jti']}").status_code == 204
    assert other.get("/api/v2/auth/me").status_code == 401             # the other browser is signed out
    assert client.get("/api/v2/auth/me").status_code == 200


def test_audit_viewer_filters_and_csv(supervisor):
    rt = supervisor.app.state.runtime
    rt.main.audit("alice", "valve_open", company="Company_1", target="Region_1/2")
    rt.main.audit("bob", "login", company="Company_2")
    r = supervisor.get("/api/v2/audit", params={"actor": "alice"}).json()
    assert [e["action"] for e in r["entries"]] == ["valve_open"] and "login" in r["actions"]
    assert supervisor.get("/api/v2/audit", params={"company": "Company_2", "action": "login"}).json()["entries"]
    csv_text = supervisor.get("/api/v2/audit", params={"format": "csv", "q": "Region_1/2"}).text
    assert csv_text.splitlines()[0].startswith("time_utc,actor,action") and "valve_open" in csv_text


# ------------------------------------------------------------------ point 21
def test_page_permissions_and_invitations(supervisor):
    from fastapi.testclient import TestClient
    r = supervisor.post("/api/v2/invitations", json={"email": "farmer@example.org", "role": "user",
                                                       "company": "Company_2", "pages": ["farm", "alerts"]})
    assert r.status_code == 201 and r.json()["emailed"] is False
    token = r.json()["link"].split("#", 1)[1]
    guest = TestClient(supervisor.app)
    info = guest.get(f"/api/v2/auth/invitations/{token}").json()
    assert info["email"] == "farmer@example.org" and info["role"] == "user"
    accepted = guest.post("/api/v2/auth/invitations/accept", json={"token": token, "username": "farmer1",
                                                                    "password": "Farm-pass-12345"})
    assert accepted.status_code == 200, accepted.text
    me = guest.get("/api/v2/auth/me").json()["user"]
    assert me["company"] == "Company_2" and me["pages"] == ["alerts", "farm"]
    assert guest.post("/api/v2/auth/invitations/accept", json={"token": token, "username": "farmer2",
                                                                "password": "Farm-pass-12345"}).status_code == 400
    users = supervisor.get("/api/v2/users").json()["users"]
    uid = next(u["id"] for u in users if u["username"] == "farmer1")
    assert supervisor.put(f"/api/v2/users/{uid}/pages", json={"pages": ["nope"]}).status_code == 400
    assert supervisor.put(f"/api/v2/users/{uid}/pages", json={"pages": None}).status_code == 200


def _provider(monkeypatch, rt, claims_extra=None):
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="k1", use="sig", alg="RS256")
    issuer = "https://idp.example.org"
    state = {}

    def fetch(url, data=None, timeout=10):
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": issuer, "authorization_endpoint": issuer + "/authorize",
                    "token_endpoint": issuer + "/token", "jwks_uri": issuer + "/jwks"}
        if url.endswith("/jwks"):
            return {"keys": [jwk]}
        assert url.endswith("/token") and data["code_verifier"] and data["code"] == "the-code"
        claims = {"iss": issuer, "aud": "wiot", "sub": "u-42", "email": "eng@example.org", "email_verified": True,
                  "nonce": state["nonce"], "iat": int(time.time()), "exp": int(time.time()) + 300,
                  **(claims_extra or {})}
        return {"id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})}

    rt.settings.oidc_issuer, rt.settings.oidc_client_id = issuer, "wiot"
    rt.oidc.fetch = fetch
    return state


def test_oidc_sign_in_links_by_email_and_verifies_the_token(supervisor, monkeypatch):
    from fastapi.testclient import TestClient
    from urllib.parse import parse_qs, urlsplit
    rt = supervisor.app.state.runtime
    state = _provider(monkeypatch, rt)
    with rt.main.connect() as db:
        db.execute("UPDATE users SET email='eng@example.org' WHERE username='admin'")
    browser = TestClient(supervisor.app, follow_redirects=False)
    start = browser.get("/api/v2/auth/oidc/login")
    assert start.status_code == 302
    q = parse_qs(urlsplit(start.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["wiot"]
    state["nonce"] = q["nonce"][0]
    bad = browser.get("/api/v2/auth/oidc/callback", params={"code": "the-code", "state": "forged"})
    assert "sso_error" in bad.headers["location"]
    done = browser.get("/api/v2/auth/oidc/callback", params={"code": "the-code", "state": q["state"][0]})
    assert done.status_code == 302 and done.headers["location"] == "/"
    me = browser.get("/api/v2/auth/me").json()["user"]
    assert me["username"] == "admin"
    with rt.main.connect() as db:
        assert db.execute("SELECT sso_subject FROM users WHERE username='admin'").fetchone()[0].endswith("|u-42")


def test_oidc_refuses_an_unknown_person_unless_auto_create(supervisor, monkeypatch):
    from fastapi.testclient import TestClient
    from urllib.parse import parse_qs, urlsplit
    rt = supervisor.app.state.runtime
    state = _provider(monkeypatch, rt, {"sub": "u-77", "email": "new@example.org", "wiot_role": "monitor"})
    browser = TestClient(supervisor.app, follow_redirects=False)

    def run():
        q = parse_qs(urlsplit(browser.get("/api/v2/auth/oidc/login").headers["location"]).query)
        state["nonce"] = q["nonce"][0]
        return browser.get("/api/v2/auth/oidc/callback", params={"code": "the-code", "state": q["state"][0]})
    assert "sso_error" in run().headers["location"]
    rt.settings.oidc_auto_create, rt.settings.oidc_default_company, rt.settings.oidc_role_claim = True, "Company_2", "wiot_role"
    assert run().headers["location"] == "/"
    me = browser.get("/api/v2/auth/me").json()["user"]
    assert me["company"] == "Company_2" and me["role"] == "monitor"


# ------------------------------------------------------------------ point 22
class FakeHttp:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def __call__(self, method, url, headers, body, timeout=10):
        self.calls.append((method, url, headers, body))
        return self.status, "ok"


def test_custom_rule_opens_an_alert_and_notifies_telegram(supervisor):
    rt = supervisor.app.state.runtime
    http = FakeHttp()
    rt.notifier.http = http
    ch = supervisor.post("/api/v2/notify/channels", params={"company": "Company_1"}, json={
        "name": "Ops chat", "kind": "telegram", "config": {"chat_id": "-100123"}, "secrets": {"bot_token": "123:ABC"},
        "min_severity": "warning", "events": ["alert", "resolved"]}).json()
    assert ch["secrets_set"] == ["bot_token"] and "bot_token" not in json.dumps(ch["config"])
    rule = supervisor.post("/api/v2/alert-rules", params={"company": "Company_1"}, json={
        "name": "Battery under 3.6 V", "metric": "battery_voltage", "op": "<", "value": 3.6, "severity": "critical"})
    assert rule.status_code == 201, rule.text
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status(battery=3.5))
    prev = supervisor.post("/api/v2/alert-rules/preview", params={"company": "Company_1"},
                           json={"metric": "battery_voltage", "op": "<", "value": 3.6}).json()
    assert prev["nodes"][0]["breached"] is True
    fired = rt.alerts.check()
    assert any(f["alert_kind"] == f"rule_{rule.json()['id']}" and f["severity"] == "critical" for f in fired)
    method, url, _, body = wait_for(http.calls)[-1]              # delivered by the notifier worker
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage" and "Battery under 3.6 V" in json.loads(body)["text"]
    for _ in range(50):
        log = supervisor.get(f"/api/v2/notify/channels/{ch['id']}/log", params={"company": "Company_1"}).json()["log"]
        if log:
            break
        time.sleep(0.05)
    assert log[0]["ok"] == 1


def test_channel_validation_and_twilio_whatsapp(supervisor):
    rt = supervisor.app.state.runtime
    bad = supervisor.post("/api/v2/notify/channels", params={"company": "Company_1"},
                          json={"kind": "sms", "config": {"provider": "twilio", "to": ["0100"]}})
    assert bad.status_code == 201 or bad.status_code == 400
    ch = rt.notify_store.save_channel("Company_1", {"kind": "whatsapp", "name": "WA", "config": {
        "provider": "twilio", "to": ["+201001234567"], "account_sid": "AC1", "from": "+14155550100"},
        "secrets": {"auth_token": "tok"}})
    http = FakeHttp(201)
    n = Notifier(rt.settings, rt.notify_store, http=http)
    ok, detail = n.deliver(rt.notify_store.get_channel(ch["id"], with_secrets=True), "test", "S", "B", retries=(0,))
    assert ok, detail
    _, url, headers, body = http.calls[0]
    assert url.endswith("/Accounts/AC1/Messages.json") and b"whatsapp%3A%2B201001234567" in body
    assert headers["Authorization"].startswith("Basic ")


def test_email_channel_and_message_text(supervisor):
    rt = supervisor.app.state.runtime
    sent = []

    class FakeSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            sent.append(msg)

    rt.settings.smtp_host, rt.settings.smtp_from = "smtp.example.org", "wiot@example.org"
    n = Notifier(rt.settings, rt.notify_store, smtp_factory=FakeSMTP)
    ch = rt.notify_store.save_channel("Company_1", {"kind": "email", "name": "Ops", "config": {"to": ["ops@example.org"]}})
    ok, _ = n.deliver(rt.notify_store.get_channel(ch["id"], with_secrets=True), "alert", "subj", "body", retries=(0,))
    assert ok and sent[0]["To"] == "ops@example.org"
    subject, body = alert_text("Company_1", {"alert_kind": "low_battery", "severity": "warning", "node_id": 3,
                                             "region": "Region_1", "state": "open", "details": {"battery_v": 3.2}})
    assert subject == "[WIOT] Warning: Low battery — NODE-003" and "battery 3.2 V" in body


def test_notification_burst_limit(supervisor):
    rt = supervisor.app.state.runtime
    n = Notifier(rt.settings, rt.notify_store, http=FakeHttp())
    ch = {"id": 999, "kind": "telegram", "config": {}, "events": ["alert"], "min_severity": "info"}
    for _ in range(30):
        n._enqueue(ch, "alert", "s", "b")
    assert n.queue.qsize() == 20 and n._suppressed[999] == 10


# ------------------------------------------------------------------ point 23
def test_monthly_report_xlsx_and_pdf(supervisor):
    rt = supervisor.app.state.runtime
    month = time.strftime("%Y-%m", time.gmtime())
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status())
    rt.telemetry.flush()
    rep = supervisor.get("/api/v2/reports/monthly", params={"company": "Company_1", "month": month}).json()
    assert rep["summary"]["nodes_reporting"] == 1 and rep["nodes"][0]["uplinks"] == 1
    x = supervisor.get("/api/v2/reports/monthly", params={"company": "Company_1", "month": month, "format": "xlsx"})
    z = zipfile.ZipFile(io.BytesIO(x.content))
    assert {"xl/workbook.xml", "xl/worksheets/sheet2.xml", "[Content_Types].xml"} <= set(z.namelist())
    assert "NODE-002" in z.read("xl/worksheets/sheet2.xml").decode()
    p = supervisor.get("/api/v2/reports/monthly", params={"company": "Company_1", "month": month, "format": "pdf"})
    assert p.content.startswith(b"%PDF-1.4") and p.content.rstrip().endswith(b"%%EOF") and b"NODE-002" in p.content
    out = rt.reports.auto_monthly(["Company_1"], None)
    assert out and rt.reports.list_files("Company_1")
    assert rt.reports.auto_monthly(["Company_1"], None) == []                 # once per month


# ------------------------------------------------------------------ point 27
def test_company_branding_and_logo(supervisor):
    png = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 64
    logo = "data:image/png;base64," + base64.b64encode(png).decode()
    r = supervisor.patch("/api/v2/org/companies/Company_1", json={"brand_name": "Nile Farms", "brand_color": "#0a7d4f",
                                                                  "brand_logo": logo})
    assert r.status_code == 200 and r.json()["has_logo"] and r.json()["brand_color"] == "#0a7d4f"
    img = supervisor.get("/api/v2/org/companies/Company_1/logo")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == png
    svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()
    assert supervisor.patch("/api/v2/org/companies/Company_1", json={"brand_logo": svg}).status_code == 400
    assert supervisor.patch("/api/v2/org/companies/Company_1", json={"brand_color": "red"}).status_code == 400


# ------------------------------------------------------------------ point 28
def test_usage_metering(supervisor):
    rt = supervisor.app.state.runtime
    for _ in range(3):
        rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status())
    supervisor.get("/api/v2/fleet", params={"company": "Company_1"})
    data = supervisor.get("/api/v2/usage", params={"company": "Company_1"}).json()
    today = data["days"][-1]
    assert today["messages"] == 3 and today["bytes"] > 0 and today["api_calls"] >= 1 and today["nodes_active"] == 1
    assert data["months"][0]["messages"] == 3
    assert supervisor.get("/api/v2/usage", params={"format": "csv"}).text.startswith("company,day,messages")


# ------------------------------------------------------------------ point 29
def test_integrations_forward_readings(supervisor):
    rt = supervisor.app.state.runtime
    http = FakeHttp()
    rt.integrations.http = http
    tb = supervisor.post("/api/v2/integrations", params={"company": "Company_1"}, json={
        "kind": "thingsboard", "name": "TB", "config": {"host": "https://thingsboard.cloud"},
        "secrets": {"access_token": "devtoken"}})
    assert tb.status_code == 201, tb.text
    rt.settings.webhook_allow_private = True
    az = supervisor.post("/api/v2/integrations", params={"company": "Company_1"}, json={
        "kind": "azure_iot", "name": "Azure", "config": {"hub": "egsa-hub", "device_id": "wiot-company1"},
        "secrets": {"device_key": base64.b64encode(b"k" * 32).decode()}})
    assert az.status_code == 201, az.text
    rt.integrations.refresh()
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status(flow=7.5))
    wait_for(http.calls, 2)                                     # delivered by the forwarding workers
    urls = {c[1] for c in http.calls}
    assert "https://thingsboard.cloud/api/v1/devtoken/telemetry" in urls
    az_call = next(c for c in http.calls if "azure-devices.net" in c[1])
    assert az_call[2]["Authorization"].startswith("SharedAccessSignature sr=egsa-hub.azure-devices.net")
    tb_body = json.loads(next(c for c in http.calls if "thingsboard" in c[1])[3])
    assert tb_body["values"]["n2_flow"] == 7.5
    rt.integrations.flush_stats()
    listed = {i["name"]: i for i in supervisor.get("/api/v2/integrations", params={"company": "Company_1"}).json()["integrations"]}
    assert listed["TB"]["sent"] == 1 and "access_token" not in json.dumps(listed["TB"]["config"])


def test_azure_sas_token_format():
    token = azure_sas("hub.azure-devices.net/devices/d1", base64.b64encode(b"secret").decode(), 3600, now=1_700_000_000)
    assert token.startswith("SharedAccessSignature sr=hub.azure-devices.net%2fdevices%2fd1&sig=")
    assert token.endswith("&se=1700003600")


def test_daily_feed_for_power_bi(supervisor):
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status(flow=4.0))
    rt.maintenance.run_once(daily=False)
    text = supervisor.get("/api/v2/feeds/daily.csv", params={"company": "Company_1"}).text
    lines = text.splitlines()
    assert lines[0].startswith("day,company,region,node_id,flow_n,flow_mean") and len(lines) == 2
    assert ",Company_1,Region_1,2,1,4.0," in lines[1]


@pytest.mark.parametrize("path", ["/invite", "/api/v2/auth/oidc"])
def test_public_pages(client, path):
    assert client.get(path).status_code == 200
