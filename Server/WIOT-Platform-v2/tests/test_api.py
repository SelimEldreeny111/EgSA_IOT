"""HTTP API: authentication, authorisation, tenant isolation, validation."""
from __future__ import annotations

from conftest import PASSWORDS, login


def test_health_and_ready(client):
    assert client.get("/healthz").json()["status"] == "ok"
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["checks"]["database"] == "ok"


def test_requires_authentication(client):
    assert client.get("/api/v2/fleet").status_code == 401
    assert client.get("/api/v2/messages").status_code == 401
    assert client.get("/", follow_redirects=False).status_code in (302, 307)


def test_login_rejects_bad_password_and_throttles(client):
    for _ in range(8):
        assert client.post("/api/v2/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    r = client.post("/api/v2/auth/login", json={"username": "admin", "password": PASSWORDS["WIOT_ADMIN_PASSWORD"]})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_cookie_mutations_require_csrf(client):
    login(client, "admin", PASSWORDS["WIOT_ADMIN_PASSWORD"])
    r = client.post("/api/v2/commands", json={"node_id": 1, "cmd_type": "GOSTM"})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]


def test_bearer_token_works_without_csrf(client):
    token = client.post("/api/v2/auth/login", json={"username": "admin",
                        "password": PASSWORDS["WIOT_ADMIN_PASSWORD"]}).json()["token"]
    client.cookies.clear()
    r = client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "admin"


def test_tenant_isolation_for_company_admin(client):
    csrf = login(client, "admin", PASSWORDS["WIOT_ADMIN_PASSWORD"])  # Company_1 admin
    assert client.get("/api/v2/fleet", params={"company": "Company_2"}).status_code == 403
    assert client.get("/api/v2/fleet", params={"company": "Company_1"}).status_code == 200
    r = client.post("/api/v2/commands", json={"company": "Company_2", "node_id": 1, "cmd_type": "GOSTM"},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403
    assert client.post("/api/v2/broker/connect", json={}, headers={"X-CSRF-Token": csrf}).status_code == 403


def test_global_monitor_reads_all_but_cannot_command(client):
    csrf = login(client, "Super_User", PASSWORDS["WIOT_MONITOR_PASSWORD"])
    assert client.get("/api/v2/fleet", params={"company": "Company_2"}).status_code == 200
    r = client.post("/api/v2/commands", json={"company": "Company_1", "node_id": 1, "cmd_type": "GOSTM"},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403


def test_command_validation(supervisor):
    bad = [
        {"node_id": 1, "cmd_type": "NOPE"},
        {"node_id": 1, "cmd_type": "SRATE", "cmd_data": 2},
        {"node_id": 1, "cmd_type": "VALVE", "cmd_data": 7},
        {"node_id": 1, "cmd_type": "FLASH_STATUS", "broadcast": True},
        {"node_id": 1, "cmd_type": "SRATE", "cmd_data": 60, "delivery": "next_wake", "broadcast": True},
        {"node_id": 0, "cmd_type": "GOSTM"},
    ]
    for body in bad:
        assert supervisor.post("/api/v2/commands", json={"company": "Company_1", **body}).status_code in (400, 422), body


def test_now_command_needs_broker_but_queue_does_not(supervisor):
    r = supervisor.post("/api/v2/commands", json={"company": "Company_1", "node_id": 3, "cmd_type": "GOSTM"})
    assert r.status_code == 503
    r = supervisor.post("/api/v2/commands", json={"company": "Company_1", "node_id": 3, "cmd_type": "SRATE",
                                                  "cmd_data": 120, "delivery": "next_wake"})
    assert r.status_code == 202 and r.json()["queued"] is True
    listed = supervisor.get("/api/v2/commands", params={"company": "Company_1", "node_id": 3}).json()["commands"]
    assert listed[0]["state"] == "pending" and listed[0]["cmd_name"] == "SRATE"


def test_user_management_and_password_policy(supervisor):
    weak = supervisor.post("/api/v2/users", json={"username": "op1", "password": "short", "role": "user"})
    assert weak.status_code == 422
    ok = supervisor.post("/api/v2/users", json={"username": "op1", "password": "Operator-pass-1",
                                                "role": "user", "company": "Company_2"})
    assert ok.status_code == 201
    users = supervisor.get("/api/v2/users").json()["users"]
    target = next(u for u in users if u["username"] == "op1")
    assert target["company"] == "Company_2"
    protected = next(u for u in users if u["username"] == "Super_User")
    assert supervisor.delete(f"/api/v2/users/{protected['id']}").status_code == 403
    assert supervisor.delete(f"/api/v2/users/{target['id']}").status_code == 204
    actions = [a["action"] for a in supervisor.get("/api/v2/audit").json()["entries"]]
    assert "user_created" in actions and "user_deleted" in actions


def test_password_change_revokes_old_session(client):
    first = client.post("/api/v2/auth/login", json={"username": "admin",
                        "password": PASSWORDS["WIOT_ADMIN_PASSWORD"]}).json()
    old_token = first["token"]
    r = client.post("/api/v2/auth/password", json={"current_password": PASSWORDS["WIOT_ADMIN_PASSWORD"],
                    "new_password": "Brand-new-pass-9"}, headers={"X-CSRF-Token": first["csrf"]})
    assert r.status_code == 200
    client.cookies.clear()
    assert client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401


def test_csv_export_neutralises_formulas(supervisor, app):
    store = app.state.runtime.telemetry
    store.save_message(company="Company_1", region="Region_1", received_at=1_790_000_000, msg_type="Command",
                       node_id=1, sensor_id="-", fields={"details": "=HYPERLINK(\"x\")"})
    text = supervisor.get("/api/v2/export.csv", params={"company": "Company_1"}).text
    assert "'=HYPERLINK" in text


def test_metrics_and_security_headers(client):
    r = client.get("/metrics")
    assert r.status_code == 200 and "wiot_messages_ingested_total" in r.text
    h = client.get("/healthz").headers
    assert h["X-Frame-Options"] == "DENY" and "default-src 'self'" in h["Content-Security-Policy"]
    assert "X-Request-ID" in h
