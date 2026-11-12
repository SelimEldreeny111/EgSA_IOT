"""Flash-download diagnosis (R2.1, point 3): merge the server's records with the gateway's serial log.

During a history download (FLASH_TODAY) every row the node sends must be stored by the server, which
then publishes a HISTORY_ACK; the gateway receives it over MQTT (``command_rx``), wakes the node and
transmits it (``downlink_wake_begin`` / ``downlink_wake_complete``); the node then sends the next row.
This tool puts those steps on one timeline so the place where acknowledgements are lost is visible:

* ACK published by the server but no ``command_rx`` at the gateway  -> broker / bridge / gateway MQTT
* ``command_rx`` but no ``downlink_wake_complete command=1``         -> gateway radio path
* transmitted by the gateway but the node resends the same row       -> radio link or node wake timing

Inputs: the server's databases and JSON log (read-only) and, optionally, the gateway serial log saved by
a terminal program (lines starting with a time stamp such as ``11/9/2026 12:38:11.402 [RX] - ...``).
Usage:  python -m wiot flash-timeline --company Company_1 --node 2 --since "2026-11-09 12:30"
                                      --until "2026-11-09 12:50" --gateway-log gateway.txt
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FLASH_IDS = (9, 10, 11, 12, 13)
TS_SLASH = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})[ T](\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?")
TS_ISO = re.compile(r"^\s*\[?(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?")
GW = [
    (re.compile(r"command_rx request=(\d+) command=(\w+) target=(\d+)"), "gateway", "command received over MQTT"),
    (re.compile(r"command_forwarded request=(\d+) target=(\d+)"), "gateway", "command forwarded to the radio"),
    (re.compile(r"failed to forward MQTT CMD over LoRa"), "gateway", "FORWARD FAILED"),
    (re.compile(r"downlink_wake_begin .*bytes=(\d+)"), "gateway", "wake probe + command: start"),
    (re.compile(r"downlink_wake_complete probe=(\d) command=(\d)"), "gateway", "wake probe + command: done"),
    (re.compile(r"rx_complete source=(\d+) message=(\d+) type=(\w+) fragments=(\d+) bytes=(\d+)"), "gateway",
     "radio message received"),
    (re.compile(r"tx topic=(\S+) bytes=(\d+)"), "gateway", "published to MQTT"),
]


def parse_local(text: str, tz) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=tz).timestamp())


def _stamp(line: str, tz) -> float | None:
    m = TS_SLASH.match(line)
    if m:
        mo, d, y, h, mi, s, frac = m.groups()
    else:
        m = TS_ISO.match(line)
        if not m:
            return None
        y, mo, d, h, mi, s, frac = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((frac or "0").ljust(6, "0")[:6]), tz)
    return dt.timestamp()


def gateway_events(path: Path, node: int, tz, start: float, end: float) -> list[dict]:
    out, last = [], None
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        ts = _stamp(raw, tz)
        last = ts if ts is not None else last
        if last is None or not start <= last <= end:
            continue
        for rx, who, what in GW:
            m = rx.search(raw)
            if not m:
                continue
            g = m.groups()
            if what == "command received over MQTT":
                if int(g[2]) not in (node, 0):
                    break
                what = f"{what}: {g[1]} request {g[0]}"
            elif what == "command forwarded to the radio":
                if int(g[1]) not in (node, 0):
                    break
                what = f"{what}: request {g[0]}"
            elif what.startswith("wake probe + command: done"):
                what = f"{what} (probe {'sent' if g[0] == '1' else 'FAILED'}, command {'sent' if g[1] == '1' else 'FAILED'})"
            elif what == "radio message received":
                if int(g[0]) != node:
                    break
                what = f"{what}: {g[2]} from node {g[0]} ({g[3]} fragments, {g[4]} B)"
            elif what == "published to MQTT":
                what = f"{what}: {g[0]} ({g[1]} B)"
            out.append({"t": last, "who": who, "what": what})
            break
    return out


def server_events(settings, company: str, region: str, node: int, start: int, end: int) -> list[dict]:
    out = []
    if not Path(settings.command_db).exists():
        return out
    with closing(sqlite3.connect(f"file:{Path(settings.command_db).as_posix()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT c.request_id, c.cmd_type, e.event, e.timestamp, e.details FROM pending_commands c "
            "JOIN command_events e ON e.request_id=c.request_id WHERE c.company=? AND c.region=? AND c.node_id=? "
            f"AND c.cmd_id IN ({','.join('?' * len(FLASH_IDS))}) AND e.timestamp BETWEEN ? AND ? ORDER BY e.id",
            (company, region, node, *FLASH_IDS, start, end)).fetchall()
    for r in rows:
        out.append({"t": r["timestamp"], "who": "server", "what": f"{r['cmd_type']} request {r['request_id']}: {r['event']}"
                    + (f" ({r['details']})" if r["details"] else "")})
    log = Path(settings.log_dir) / "wiot-server.log"
    marker = f"[FLASH] {company}/{region}/{node} reply persisted; history ACK="
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if marker not in line:
                continue
            try:
                rec = json.loads(line)
                t = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp()
            except (ValueError, KeyError):
                continue
            if start <= t <= end:
                sent = rec["msg"].rsplit("history ACK=", 1)[-1].startswith("True")
                out.append({"t": t, "who": "server", "what": "history row stored; HISTORY_ACK "
                            + ("published" if sent else "NOT published (broker down or no ACK required)")})
    return out


def timeline(settings, company: str, region: str, node: int, since: str, until: str,
             gateway_log: Path | None = None, tz_name: str = "Africa/Cairo") -> dict:
    tz = ZoneInfo(tz_name)
    start, end = parse_local(since, tz), parse_local(until, tz)
    events = server_events(settings, company, region, node, start, end)
    if gateway_log:
        events += gateway_events(gateway_log, node, tz, start, end)
    events.sort(key=lambda e: (e["t"], e["who"] != "server"))
    acks = sum(1 for e in events if e["what"].startswith("history row stored; HISTORY_ACK published"))
    gw_rx = sum(1 for e in events if "command received over MQTT: HISTORY_ACK" in e["what"])
    radio = sum(1 for e in events if e["what"].startswith("wake probe + command: done (probe sent, command sent)"))
    summary = {"history_acks_published": acks}
    if gateway_log:
        summary.update(history_acks_at_gateway=gw_rx, downlinks_transmitted=radio)
        summary["reading"] = (
            "ACKs are lost before the gateway (broker, bridge or gateway MQTT)" if acks and gw_rx < acks else
            "the gateway receives the ACKs but does not transmit all of them" if gw_rx and radio < gw_rx else
            "ACKs reach the radio; if the node still resends rows, the loss is on the radio link or in the node's "
            "wake timing" if acks else "no history ACKs in this window")
    for e in events:
        e["local"] = datetime.fromtimestamp(e["t"], tz).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return {"company": company, "region": region, "node": node, "since": since, "until": until,
            "summary": summary, "events": events}


def format_text(result: dict) -> str:
    lines = [f"Flash download timeline  {result['company']}/{result['region']}/node {result['node']}  "
             f"{result['since']} .. {result['until']}", ""]
    lines += [f"{e['local']}  {e['who']:<8} {e['what']}" for e in result["events"]] or ["(no events)"]
    lines += ["", "Summary: " + json.dumps(result["summary"], ensure_ascii=False)]
    return "\n".join(lines)
