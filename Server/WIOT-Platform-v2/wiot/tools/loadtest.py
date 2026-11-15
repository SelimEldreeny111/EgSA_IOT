"""Load test: N simulated nodes against a throw-away server (R2.2, point 11).

``python -m wiot loadtest --nodes 200 --rate 1 --minutes 2`` starts, all on localhost and in a temporary
data folder that is deleted afterwards:

1. the development MQTT broker (``wiot devbroker``) on ``--broker-port``;
2. a server subprocess (``wiot serve``) on ``--port`` with a random AES key, a random admin password and
   ``WIOT_INGEST_BATCH_MS=--batch-ms``; it never touches the real data folder or the field broker;
3. N encrypted virtual nodes (the fleet simulator) publishing ``--rate`` uplinks per node per minute.

While the fleet runs, a reader polls the dashboard's heaviest calls (fleet, 24 h series, message page) and
records their latency. The report gives offered and stored message rates, loss, ingest latency (server
histogram) and API p50/p95/max, as JSON (``--out``) and a summary on the console. Exit code 1 when more than
1 % of the published messages were not stored or the API p95 exceeds 1 s.
"""
from __future__ import annotations

import json
import os
import random
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

COMPANY = "Company_1"
REGION = "Region_1"


def _wait_port(port: int, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"port {port} did not open within {timeout} s")


class Api:
    def __init__(self, base: str):
        self.base = base
        self.token = ""

    def call(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw) if raw[:1] in (b"{", b"[") else {"text": raw.decode()}

    def metric(self, name: str) -> float:
        with urllib.request.urlopen(self.base + "/metrics", timeout=10) as resp:
            text = resp.read().decode()
        return sum(float(line.rsplit(" ", 1)[1]) for line in text.splitlines()
                   if line.startswith(name) and not line.startswith("#"))


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def run(nodes: int, rate: float, minutes: float, batch_ms: int, port: int, broker_port: int) -> dict:
    from ..sim.fleet import FleetSimulator, VirtualNode

    work = Path(tempfile.mkdtemp(prefix="wiot-loadtest-"))
    key = secrets.token_hex(16)
    password = f"Lt-{secrets.token_hex(10)}-Aa9"              # throw-away; satisfies the password policy
    env = {**os.environ, "WIOT_DATA_DIR": str(work / "data"), "WIOT_PORT": str(port), "WIOT_HOST": "127.0.0.1",
           "WIOT_MQTT_AUTOCONNECT": "true", "WIOT_MQTT_HOST": "127.0.0.1", "WIOT_MQTT_PORT": str(broker_port),
           "WIOT_MQTT_AES_KEY_HEX": key, "WIOT_ADMIN_PASSWORD": password, "WIOT_SUPERVISOR_PASSWORD": password,
           "WIOT_MONITOR_PASSWORD": password, "WIOT_INGEST_BATCH_MS": str(batch_ms),
           "WIOT_CLOCK_SYNC": "false", "WIOT_CONFIG_WATCH": "false", "WIOT_WEATHER_ENABLED": "false",
           "WIOT_ENV": "development", "WIOT_MQTT_CLIENT_ID": f"wiot_loadtest_{port}", "PYTHONIOENCODING": "utf-8"}
    for name in ("WIOT_MQTT_USERNAME", "WIOT_MQTT_PASSWORD", "WIOT_TLS_CERTFILE", "WIOT_TLS_KEYFILE"):
        env.pop(name, None)
    procs = []
    sim = None
    try:
        procs.append(subprocess.Popen([sys.executable, "-m", "wiot", "devbroker", "--port", str(broker_port)],
                                      env=env, cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        _wait_port(broker_port)
        server_log = open(work / "server.log", "wb")
        procs.append(subprocess.Popen([sys.executable, "-m", "wiot", "serve", "--port", str(port)], env=env,
                                      cwd=work, stdout=server_log, stderr=subprocess.STDOUT))
        try:
            _wait_port(port, 60)
        except RuntimeError:
            server_log.flush()
            raise RuntimeError("server did not start: " + (work / "server.log").read_text(errors="replace")[-3000:])
        api = Api(f"http://127.0.0.1:{port}")
        deadline = time.time() + 30
        while time.time() < deadline:
            if api.call("/readyz").get("checks", {}).get("broker") == "connected":
                break
            time.sleep(0.5)
        api.token = api.call("/api/v2/auth/login", {"username": "admin", "password": password})["token"]

        report_s = 60.0 / rate
        fleet = [VirtualNode(COMPANY, REGION, i, "normal", report_s, random.Random(i), soil=i % 2 == 0,
                             ec=i % 3 == 0) for i in range(1, nodes + 1)]
        sim = FleetSimulator("127.0.0.1", broker_port, bytes.fromhex(key), fleet, drop_rate=0.0,
                             stagger_s=report_s / max(1, nodes))         # spread the first reports over one interval
        runner = threading.Thread(target=sim.run, daemon=True)
        ingest_before = api.metric("wiot_messages_ingested_total")
        started = time.time()
        runner.start()

        latencies: dict[str, list[float]] = {"fleet": [], "series_24h": [], "messages": []}
        calls = {"fleet": f"/api/v2/fleet?company={COMPANY}&region={REGION}",
                 "series_24h": f"/api/v2/nodes/1/series?company={COMPANY}&region={REGION}&metric=flow&hours=24",
                 "messages": f"/api/v2/messages?company={COMPANY}&region={REGION}&page_size=50"}
        errors = 0
        while time.time() - started < minutes * 60:
            for name, path in calls.items():
                t0 = time.perf_counter()
                try:
                    api.call(path)
                    latencies[name].append((time.perf_counter() - t0) * 1000)
                except Exception:
                    errors += 1
            time.sleep(1.0)
        sim.stop()
        runner.join(timeout=10)
        time.sleep(max(2.0, batch_ms / 1000 * 4))          # let queued writes commit
        elapsed = time.time() - started
        stored = api.metric("wiot_messages_ingested_total") - ingest_before
        ingest_sum = api.metric("wiot_ingest_seconds_sum")
        ingest_count = api.metric("wiot_ingest_seconds_count") or 1
        sent = sim.sent
        all_lat = [v for vs in latencies.values() for v in vs]
        return {
            "nodes": nodes, "rate_per_node_per_min": rate, "minutes": round(elapsed / 60, 2), "batch_ms": batch_ms,
            "published": sent, "stored": int(stored), "loss_pct": round(100 * max(0, sent - stored) / sent, 2) if sent else 0,
            "offered_msgs_per_s": round(sent / elapsed, 1), "stored_msgs_per_s": round(stored / elapsed, 1),
            "ingest_mean_ms": round(1000 * ingest_sum / ingest_count, 2),
            "api": {name: {"n": len(v), "p50_ms": round(_pct(v, 0.5), 1), "p95_ms": round(_pct(v, 0.95), 1),
                           "max_ms": round(max(v), 1) if v else 0} for name, v in latencies.items()},
            "api_p95_ms": round(_pct(all_lat, 0.95), 1), "api_errors": errors,
            "python": sys.version.split()[0], "platform": sys.platform,
        }
    finally:
        if "server_log" in locals():
            server_log.close()
        if sim is not None:
            sim.stop()
        for p in reversed(procs):
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(work, ignore_errors=True)


def main(args) -> int:
    print(f"Load test: {args.nodes} nodes x {args.rate}/min for {args.minutes} min "
          f"(batch {args.batch_ms} ms) on ports {args.port}/{args.broker_port} ...", flush=True)
    result = run(args.nodes, args.rate, args.minutes, args.batch_ms, args.port, args.broker_port)
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    ok = result["loss_pct"] <= 1.0 and result["api_p95_ms"] <= 1000
    print("PASS" if ok else "FAIL", "- loss", f"{result['loss_pct']} %,", "API p95", f"{result['api_p95_ms']} ms")
    return 0 if ok else 1

