"""Shared fixtures: an isolated data directory and an authenticated client."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASSWORDS = {
    "WIOT_ADMIN_PASSWORD": "Admin-pass-123",
    "WIOT_SUPERVISOR_PASSWORD": "Super-pass-123",
    "WIOT_MONITOR_PASSWORD": "Monit-pass-123",
}
AES_KEY = "00112233445566778899aabbccddeeff"


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    from wiot.config import Settings

    for key, value in PASSWORDS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WIOT_MQTT_AUTOCONNECT", "false")
    monkeypatch.setenv("WIOT_WEATHER_ENABLED", "false")  # no network in tests
    monkeypatch.setenv("WIOT_ALERT_MONITOR", "false")  # no background fleet polling in tests
    monkeypatch.setenv("WIOT_SECRET_KEY", "test-secret-key-that-is-long-enough-0123456789")
    return Settings(_env_file=None, data_dir=tmp_path / "data", mqtt_aes_key_hex=AES_KEY)


@pytest.fixture()
def app(settings):
    from wiot.app import create_app

    return create_app(settings)


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def login(client, username, password):
    r = client.post("/api/v2/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrf"]


@pytest.fixture()
def supervisor(client):
    csrf = login(client, "EgSA_Supervisor", PASSWORDS["WIOT_SUPERVISOR_PASSWORD"])
    client.headers["X-CSRF-Token"] = csrf
    return client
