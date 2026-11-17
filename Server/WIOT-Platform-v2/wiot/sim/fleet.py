"""Encrypted WIOT fleet simulator for demos, load and end-to-end tests.

Each virtual node speaks the real wire contract (AES-128-CBC framed protobuf
on ``wiot/<company>/<region>/<node>/{status,data,cmd}``), follows a power
profile, and only executes commands while its receiver is awake — exactly the
behaviour the delivery-risk model learns from field data.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import signal
import threading
import time
from dataclasses import dataclass, field

from ..protocol import messages_pb2
from ..protocol.transport import MqttNodeClient

log = logging.getLogger("wiot.sim")

# power_mode ids follow protocol/power.py
PROFILES = {
    "normal": {"mode": 1, "awake_always": True, "battery_drain_v_per_h": 0.004},
    "rtc": {"mode": 2, "awake_always": False, "rx_window_s": 4, "battery_drain_v_per_h": 0.0008},
    "remote_wake": {"mode": 3, "awake_always": False, "rx_window_s": 6, "battery_drain_v_per_h": 0.0012},
    "queued": {"mode": 4, "awake_always": False, "rx_window_s": 5, "battery_drain_v_per_h": 0.0009},
    "wor": {"mode": 5, "awake_always": False, "rx_window_s": 8, "battery_drain_v_per_h": 0.0010},
}
CMD = {1: "SRATE", 2: "STRAN", 3: "STIME", 4: "GOSTM", 5: "VALVE", 6: "WAKE",
       7: "CLEAR_POWER_RESETS", 8: "CLEAR_WDT_RESETS"}


@dataclass
class VirtualNode:
    company: str
    region: str
    node_id: int
    profile: str
    report_s: float
    rng: random.Random
    meters: tuple[int, ...] = (1,)       # 1 = TUF, 2 = Supmea
    soil: bool = False
    ec: bool = False
    battery: float = 3.95
    valve: int = 0
    agri: bool = False            # centre-pivot zone: soil water balance + valve-driven flow
    moisture: float = 32.0        # volumetric soil water content, %
    pivot_flow: float = 180.0     # m3/h while the valve is open
    wdt_resets: int = 0
    power_resets: int = 0
    forward_l: float = 0.0
    day_l: float = 0.0
    sequence: int = 0
    awake_until: float = 0.0
    lease_until: float = 0.0
    next_report: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def mode(self) -> int:
        return PROFILES[self.profile]["mode"]

    @property
    def topic_base(self) -> str:
        return f"wiot/{self.company}/{self.region}/{self.node_id}"

    def awake(self, now: float) -> bool:
        return (PROFILES[self.profile]["awake_always"] or now < self.awake_until
                or now < self.lease_until)

    def sensor_mask(self) -> int:
        mask = 0
        mask |= 1 if 1 in self.meters else 0
        mask |= 2 if self.soil else 0
        mask |= 4 if self.ec else 0
        mask |= 8 if 2 in self.meters else 0
        return mask

    # ---------------------------------------------------------------- physics
    def _flow(self, now: float) -> float:
        hour = (time.localtime(now).tm_hour + time.localtime(now).tm_min / 60)
        demand = 0.35 + 0.65 * max(0.0, math.sin((hour - 5) / 24 * 2 * math.pi)) ** 1.6
        burst = 1.0 + (2.8 if self.rng.random() < 0.01 else 0.0)  # rare anomaly
        base = {1: 4.2, 2: 6.0, 3: 2.6}.get(self.node_id % 4, 3.5)
        return round(max(0.0, base * demand * burst * self.rng.gauss(1.0, 0.06)), 3)

    def _soil_step(self, now: float) -> float:
        """Demo-accelerated water balance: ET drying (stronger at midday) vs irrigation."""
        hour = time.localtime(now).tm_hour + time.localtime(now).tm_min / 60
        if self.valve == 1:
            self.moisture = min(47.0, self.moisture + self.rng.uniform(0.55, 0.95))
            return round(max(0.0, self.pivot_flow * self.rng.gauss(1.0, 0.025)), 1)
        et = 0.08 + 0.20 * max(0.0, math.sin((hour - 6) / 24 * 2 * math.pi))
        self.moisture = max(11.0, self.moisture - et * self.rng.uniform(0.7, 1.3))
        return 0.0

    def build_status(self, now: float, telemetry: bool = False, ack: tuple | None = None):
        dt_h = self.report_s / 3600
        flow = self._soil_step(now) if self.agri else self._flow(now)
        self.forward_l += flow * 1000 * dt_h
        self.day_l += flow * 1000 * dt_h
        self.battery = max(3.05, self.battery - PROFILES[self.profile]["battery_drain_v_per_h"] * dt_h
                           + self.rng.gauss(0, 0.004))
        self.sequence += 1
        msg = messages_pb2.Telemetry() if telemetry else messages_pb2.Status_Message()
        msg.node_id = self.node_id
        msg.sensor_id = 1
        msg.timestamp = int(now)
        msg.battery_voltage = round(self.battery, 3)
        mask = self.sensor_mask()
        msg.sensor_mask = mask
        msg.active_sensor_count = bin(mask).count("1")
        msg.node_status = self.valve
        primary = self.meters[0] if self.meters else 0
        if primary:
            msg.flow_rate = flow
            msg.velocity = round((flow / 3600) / (math.pi * 0.1 ** 2), 3) if self.agri else round(flow / 3.6 / 0.785 * 0.9, 3)
            msg.flow_rate_per_day = round(self.day_l / 1000, 3)
            msg.flow_rate_per_month = round(self.forward_l / 1000 * 0.6, 3)
            msg.flow_rate_per_year = round(self.forward_l / 1000, 3)
            msg.flow_meter_type = primary
            msg.flow_period_source = 2
            msg.flow_live_valid = True
            msg.flow_period_totals_valid = True
            msg.flow_cumulative_totals_valid = True
            msg.rtc_valid = True
            msg.forward_total_liters = int(self.forward_l)
            msg.net_total_liters = int(self.forward_l)
            msg.flow_period_quality = 1
        if len(self.meters) > 1:
            sec = msg.secondary_flow_meter
            f2 = round(flow * self.rng.uniform(0.96, 1.04), 3)
            sec.flow_rate, sec.velocity = f2, round(f2 / 3.6 / 0.785 * 0.9, 3)
            sec.flow_rate_per_day = round(self.day_l / 1000 * 1.01, 3)
            sec.flow_meter_type = self.meters[1]
            sec.flow_period_source = 2
            sec.flow_live_valid = sec.flow_period_totals_valid = sec.rtc_valid = True
            sec.flow_period_quality = 1
        hour = time.localtime(now).tm_hour + time.localtime(now).tm_min / 60
        soil_t = 22 + 6 * math.sin((hour - 9) / 24 * 2 * math.pi) - (1.5 if self.agri and self.valve == 1 else 0)
        if self.soil:
            msg.soil_temperature = round(soil_t + self.rng.gauss(0, 0.3), 2)
            msg.soil_moisture = round((self.moisture if self.agri else 34 + 3 * math.cos(now / 86400))
                                      + self.rng.gauss(0, 0.35), 2)
            msg.soil_moisture_temp_valid = 1
        if self.ec:
            msg.ec_temperature = round(soil_t + 0.6 + self.rng.gauss(0, 0.4), 2)
            msg.ec_moisture = round((self.moisture if self.agri else 38) + self.rng.gauss(0, 0.6), 2)
            # Drier soil concentrates salts: bulk EC rises as water content falls.
            ec = 620 + (40 - self.moisture) * 14 if self.agri else 850
            msg.electrical_conductivity = round(ec + self.rng.gauss(0, 10), 1)
            msg.soil_moisture_temp_ec_valid = 1
        msg.power_mode = self.mode
        msg.power_state = 1 if self.awake(now) else 2
        msg.wake_remaining_seconds = max(0, int(self.lease_until - now))
        msg.wdt_reset_count = self.wdt_resets
        msg.power_reset_count = self.power_resets
        msg.sample_sequence = self.sequence
        msg.sample_time_valid = True
        if telemetry:
            msg.sampling_rate = int(self.report_s * 1000)
            msg.Transmission_rate = int(self.report_s * 1000)
            if ack:
                request_id, cmd_id, success = ack
                msg.command_ack_request_id = request_id
                msg.command_ack_cmd_id = cmd_id
                msg.command_ack_success = success
        return msg


class VirtualDevice:
    """A third-party device (Track G) publishing plain JSON to wiotx/{company}/{device}/up."""

    def __init__(self, company: str, device_id: str, period_s: float, rng: random.Random):
        self.company, self.device_id, self.period_s, self.rng = company, device_id, period_s, rng
        self.next_report = 0.0
        self.level = rng.uniform(55, 90)          # tank level %
        self.moisture = rng.uniform(30, 40)       # substrate moisture %

    @property
    def topic(self) -> str:
        return f"wiotx/{self.company}/{self.device_id}/up"

    def payload(self, now: float) -> dict:
        hour = (now / 3600 + 2) % 24                                   # Egypt local time
        day = max(0.0, math.sin(math.pi * (hour - 6) / 12))           # 0 at night, 1 at noon
        noise = self.rng.gauss
        warm = 1.5 if "GH2" in self.device_id else 0.0
        if self.device_id.endswith("CLIMATE"):
            return {"ts": int(now), "temperature": round(19 + warm + 9 * day + noise(0, 0.3), 1),
                    "humidity": round(82 - 25 * day + noise(0, 1.2), 1), "co2": round(950 - 520 * day + noise(0, 18)),
                    "par": round(1350 * day * self.rng.uniform(0.9, 1.0)), "battery": 96}
        if self.device_id.endswith("SUBSTRATE"):
            self.moisture -= self.rng.uniform(0.02, 0.12) * (1 + day)
            if self.moisture < 28:
                self.moisture = self.rng.uniform(38, 42)               # irrigation pulse
            return {"ts": int(now), "water_SOIL": round(self.moisture, 1), "temp_SOIL": round(20 + 3 * day + noise(0, 0.2), 1),
                    "conduct_SOIL": round(2100 + 300 * day + noise(0, 40)), "BatV": 3.61}
        self.level -= self.rng.uniform(0.05, 0.3) * (1 + day)
        if self.level < 22:
            self.level = self.rng.uniform(92, 96)                      # refill
        return {"ts": int(now), "level_pct": round(self.level, 1), "distance": round(300 + (100 - self.level) * 30),
                "batv": 3.58}


def ext_devices(companies: list[str], report_s: float, seed: int) -> list[VirtualDevice]:
    from .demo_greenhouses import DEMO_COMPANY, DEVICES
    if DEMO_COMPANY not in companies:
        return []
    return [VirtualDevice(DEMO_COMPANY, d["device_id"], max(15.0, report_s * 3), random.Random(seed * 7 + i))
            for i, d in enumerate(DEVICES)]


class FleetSimulator:
    def __init__(self, host: str, port: int, key: bytes, nodes: list[VirtualNode],
                 drop_rate: float = 0.02, stagger_s: float = 0.7, devices: list[VirtualDevice] | None = None):
        self.stagger_s = stagger_s  # delay between the first reports of consecutive nodes
        self.devices = list(devices or [])
        self.nodes = {(n.company, n.region, n.node_id): n for n in nodes}
        self.drop_rate = drop_rate
        topics = sorted({f"wiot/{n.company}/{n.region}/{n.node_id}/cmd" for n in nodes}
                        | {f"wiot/{n.company}/{n.region}/broadcast" for n in nodes})
        self.client = MqttNodeClient(host, port, key, f"wiot_sim_{int(time.time())}", topics,
                                     on_plaintext=self._on_command, on_status=self._status)
        self._stop = threading.Event()
        self.sent = 0

    def _status(self, message: str) -> None:
        if message and ("Ready" in message or "FAILED" in message or "Disconnected" in message):
            log.info(message)

    def _publish(self, node: VirtualNode, msg, kind: str) -> None:
        if self.drop_rate and node.rng.random() < self.drop_rate:
            return  # simulated radio loss
        try:
            self.client.publish_plaintext(f"{node.topic_base}/{kind}", msg.SerializeToString())
        except RuntimeError as exc:
            # Broker briefly unreachable: skip this report like a lost radio frame. The paho
            # network loop reconnects and re-subscribes by itself; the fleet keeps running.
            missed = getattr(self, "missed", 0)
            if not missed:
                log.warning("Publish skipped while the broker is unreachable (%s); waiting for reconnect", exc)
            self.missed = missed + 1
            return
        if getattr(self, "missed", 0):
            log.info("Broker reachable again; %d report(s) were skipped", self.missed)
            self.missed = 0
        self.sent += 1

    def _on_command(self, topic: str, plaintext: bytes) -> None:
        parts = topic.split("/")
        cmd = messages_pb2.CMD_Message()
        cmd.ParseFromString(plaintext)
        if cmd.cmd_id == 14:
            return
        targets = ([n for k, n in self.nodes.items() if k[0] == parts[1] and k[1] == parts[2]]
                   if parts[-1] == "broadcast" else
                   [self.nodes.get((parts[1], parts[2], int(parts[3])))])
        for node in filter(None, targets):
            threading.Thread(target=self._execute, args=(node, cmd), daemon=True).start()

    def _execute(self, node: VirtualNode, cmd) -> None:
        now = time.time()
        with node.lock:
            if not node.awake(now):
                log.info("%s node %s asleep: dropped %s", node.company, node.node_id, CMD.get(cmd.cmd_id))
                return
            time.sleep(node.rng.uniform(0.4, 2.5))  # radio + execution latency
            success = cmd.cmd_id in CMD
            if cmd.cmd_id in (1, 2):
                node.report_s = max(5, min(86400, int(cmd.cmd_data)))
            elif cmd.cmd_id == 5:
                node.valve = int(cmd.cmd_data)
            elif cmd.cmd_id == 6:
                node.lease_until = time.time() + (cmd.cmd_data or 120)
            elif cmd.cmd_id == 7:
                node.power_resets = 0
            elif cmd.cmd_id == 8:
                node.wdt_resets = 0
            elif cmd.cmd_id == 4:
                node.next_report = time.time()
            reply = node.build_status(time.time(), telemetry=True,
                                      ack=(cmd.request_id, cmd.cmd_id, success) if cmd.request_id else None)
            if cmd.cmd_id == 6 and cmd.request_id:
                reply.wake_command_ack = True
                reply.wake_request_id = cmd.request_id
                reply.power_state = 1
            node.awake_until = max(node.awake_until, time.time() + 3)
        self._publish(node, reply, "data")

    def run(self) -> None:
        self.client.connect()
        deadline = time.time() + 20
        while not self.client.is_connected():
            if time.time() > deadline:
                raise RuntimeError("Broker did not confirm subscriptions within 20 s")
            time.sleep(0.2)
        now = time.time()
        for i, node in enumerate(self.nodes.values()):
            node.next_report = now + 1 + i * self.stagger_s
        for i, dev in enumerate(self.devices):
            dev.next_report = now + 2 + i
        log.info("Simulating %d nodes and %d third-party devices", len(self.nodes), len(self.devices))
        while not self._stop.is_set():
            now = time.time()
            for dev in self.devices:
                if now >= dev.next_report:
                    dev.next_report = now + dev.period_s * dev.rng.uniform(0.95, 1.05)
                    try:
                        self.client.publish_raw(dev.topic, json.dumps(dev.payload(now)).encode(), note="json device")
                        self.sent += 1
                    except RuntimeError:
                        pass                      # broker briefly unreachable: like a lost uplink
            for node in self.nodes.values():
                if now < node.next_report:
                    continue
                with node.lock:
                    if not PROFILES[node.profile]["awake_always"]:
                        node.awake_until = now + PROFILES[node.profile]["rx_window_s"]
                    if node.rng.random() < 0.002:
                        node.wdt_resets += 1
                    telemetry = node.sequence % 10 == 9
                    msg = node.build_status(now, telemetry=telemetry)
                    node.next_report = now + node.report_s * node.rng.uniform(0.97, 1.03)
                self._publish(node, msg, "data" if telemetry else "status")
            self._stop.wait(0.2)
        self.client.disconnect()

    def stop(self, *_):
        self._stop.set()


AGRI_ZONES = [  # (profile, start moisture %, valve) for pivots P-08, P-10, P-12, P-15, P-19, P-20
    ("wor", 33.0, 0), ("rtc", 24.5, 0), ("remote_wake", 36.0, 0),
    ("normal", 27.5, 0), ("rtc", 41.0, 1), ("queued", 30.0, 0),
]


def agri_fleet(company: str, region: str, report_s: float, seed: int) -> list[VirtualNode]:
    nodes = []
    for i, (profile, moisture, valve) in enumerate(AGRI_ZONES, start=1):
        rng = random.Random(seed * 1000 + i)
        nodes.append(VirtualNode(company, region, i, profile, report_s, rng, meters=(1,), soil=True,
                                 ec=i % 2 == 0, battery=rng.uniform(3.75, 4.05), valve=valve, agri=True,
                                 moisture=moisture, pivot_flow=rng.uniform(165, 195)))
    return nodes


def default_fleet(companies: list[str], region: str, report_s: float, seed: int) -> list[VirtualNode]:
    nodes = []
    for company in companies:
        if "agri" in company.lower():
            nodes += agri_fleet(company, region, report_s, seed)
    companies = [c for c in companies if "agri" not in c.lower()]
    layout = [("normal", (1,), True, False), ("rtc", (1, 2), False, True),
              ("remote_wake", (2,), True, True), ("wor", (1,), False, False)]
    for c_index, company in enumerate(companies):
        for n_index, (profile, meters, soil, ec) in enumerate(layout[: 4 - c_index]):
            rng = random.Random(seed * 100 + c_index * 10 + n_index)
            nodes.append(VirtualNode(company, region, n_index + 1, profile,
                                     report_s * (1 if profile == "normal" else 2), rng,
                                     meters=meters, soil=soil, ec=ec,
                                     battery=rng.uniform(3.7, 4.05)))
    return nodes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="WIOT encrypted fleet simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--aes-key", required=True, help="32 hex characters (same key as the server)")
    parser.add_argument("--companies", default="Company_1,Company_2")
    parser.add_argument("--region", default="Region_1")
    parser.add_argument("--report-seconds", type=float, default=10)
    parser.add_argument("--drop-rate", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s sim %(message)s")
    companies = [c.strip() for c in args.companies.split(",") if c.strip()]
    nodes = default_fleet(companies, args.region, args.report_seconds, args.seed)
    sim = FleetSimulator(args.host, args.port, bytes.fromhex(args.aes_key), nodes, args.drop_rate,
                         devices=ext_devices(companies, args.report_seconds, args.seed))
    signal.signal(signal.SIGINT, sim.stop)
    sim.run()


if __name__ == "__main__":
    main()
