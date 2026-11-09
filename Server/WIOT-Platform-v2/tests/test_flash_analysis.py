"""Flash-log analysis: projection, quality, coverage, valid-only statistics, gap recovery, API."""
import time

from wiot.domain.flash_analysis import analyse, transfer_state
from wiot.protocol import messages_pb2 as pb

NOW = 1_800_100_000


def memory(**over):
    info = {"state": 4, "state_name": "Ready", "jedec_id": 0x016017, "capacity_bytes": 8388608,
            "usable_bytes": 7332864, "used_bytes": 40 * 512, "free_bytes": 7332864 - 40 * 512,
            "record_count": 40, "maximum_records": 14322, "generation": 7, "latest_sequence": 40,
            "retention_started_epoch": NOW - 600, "next_clear_epoch": NOW - 600 + 86400,
            "dropped_samples": 79, "corrupt_records": 0, "clear_sectors_remaining": 0,
            "rtc_trusted": True, "busy": False}
    info.update(over)
    return info


def rec(gen, seq, epoch, **data):
    base = {"flow_rate": 10.0, "flow_live_valid": True, "battery_voltage": 3.7, "Transmission_rate": 15000,
            "soil_moisture": 0.0, "soil_moisture_temp_valid": 0}
    base.update(data)
    return {"generation": gen, "sequence": seq, "epoch": epoch, "day": 20261109, "data": base}


def test_memory_retention_and_quality():
    r = analyse({"memory": memory(), "received_at": NOW, "transfers": []}, [], [], NOW)
    m, ret, q = r["memory"], r["retention"], r["quality"]
    assert m["jedec_hex"] == "0x016017" and m["reserved_bytes"] == 8388608 - 7332864
    assert ret["records_per_hour"] == 240.0 and ret["projected_records"] == 5760 and ret["overflow_at"] is None
    assert ret["clears_in_s"] == 86400 - 600
    assert q == {"stored": 40, "not_logged": 79, "corrupt": 0, "not_logged_pct": 66.4, "rtc_trusted": True, "busy": False}


def test_overflow_is_projected_before_the_daily_clear():
    # 1,000 records in 10 minutes -> 6,000/h -> the 14,322 limit is hit after ~2.4 h
    r = analyse({"memory": memory(record_count=1000), "received_at": NOW, "transfers": []}, [], [], NOW)
    ret = r["retention"]
    assert ret["projected_pct"] > 100
    assert ret["overflow_at"] == int(NOW - 600 + 14322 / 6000 * 3600)


def test_no_status_means_no_memory_sections():
    r = analyse({"memory": None, "received_at": None, "transfers": []}, [], [], NOW)
    assert r["memory"] is None and r["retention"] is None and r["quality"] is None
    assert r["recovery"]["archived"] == 0 and r["series"] == []


def test_transfer_states_including_stalled():
    assert transfer_state({"complete": 1, "result": 0, "phase": 3}) == ("good", "Complete")
    assert transfer_state({"complete": 0, "result": 4, "phase": 3}) == ("critical", "Stopped · Cancelled")
    assert transfer_state({"complete": 0, "result": 0, "phase": 2, "updated": NOW - 30}, NOW) == ("warning", "Receiving")
    assert transfer_state({"complete": 0, "result": 0, "phase": 2, "updated": NOW - 7200}, NOW) == ("neutral", "Stalled")


def test_generations_metrics_and_gap_recovery():
    t0 = NOW - 5000
    records = [rec(3, 1, t0), rec(3, 2, t0 + 120), rec(3, 5, t0 + 480),               # seq 3-4 missing
               rec(4, 1, t0 + 2000, flow_live_valid=False, flow_rate=999.0),          # invalid flow ignored
               rec(4, 2, t0 + 2120, soil_moisture=31.5, soil_moisture_temp_valid=1)]
    live = [t0 + 5, t0 + 125, t0 + 470]                                              # link silent for gen 4
    r = analyse({"memory": None, "received_at": None, "transfers": []}, records, live, NOW)
    gens = {g["generation"]: g for g in r["generations"]}
    assert gens[3]["records"] == 3 and gens[3]["missing_in_range"] == 2 and gens[3]["completeness_pct"] == 60.0
    assert gens[3]["median_spacing_s"] == 240.0
    flow = next(m for m in r["metrics"] if m["key"] == "flow_rate")
    assert flow["samples"] == 4 and flow["max"] == 10.0                                # 999 had no validity flag
    soil = next(m for m in r["metrics"] if m["key"] == "soil_moisture")
    assert soil["samples"] == 1 and soil["mean"] == 31.5
    rc = r["recovery"]
    assert rc["tolerance_s"] == 60 and rc["covered"] == 3 and rc["recovered"] == 2
    assert rc["recovered_windows"] == [{"start": t0 + 2000, "end": t0 + 2120, "samples": 2}]
    assert [p["flow_rate"] for p in r["series"]][3] is None


def _status(now):
    msg = pb.Telemetry(node_id=2)
    msg.flash_log.CopyFrom(pb.FlashLogInfo(state=4, jedec_id=0x016017, capacity_bytes=8388608, usable_bytes=7332864,
                                           used_bytes=1024, free_bytes=7332864 - 1024, record_count=2,
                                           maximum_records=14322, generation=4, latest_sequence=2,
                                           retention_started_epoch=now - 3600, next_clear_epoch=now - 3600 + 86400,
                                           dropped_samples=3, rtc_trusted=True))
    return msg


def _row(seq, total, now):
    msg = pb.Telemetry(node_id=2, timestamp=now - 600 + seq * 60, flow_rate=12.5, flow_live_valid=True,
                       battery_voltage=3.7, sample_sequence=seq, stored_sample=True, sample_time_valid=True)
    msg.history.CopyFrom(pb.HistoryInfo(request_id=91, generation=4, sequence=seq, index=seq, total=total,
                                        day_key=20261109, kind=2, phase=2, ack_required=True))
    return msg


def test_flash_api_reports_status_downloads_and_analysis(supervisor, app):
    ingest, now = app.state.runtime.ingest, int(time.time())
    ingest.on_plaintext("wiot/Company_1/Region_1/2/data", _status(now).SerializeToString())
    for seq in (1, 2):
        ingest.on_plaintext("wiot/Company_1/Region_1/2/data", _row(seq, 2, now).SerializeToString())

    nodes = supervisor.get("/api/v2/flash/nodes", params={"company": "Company_1"})
    assert nodes.status_code == 200 and nodes.json()["nodes"] == [2]
    r = supervisor.get("/api/v2/flash/analysis", params={"company": "Company_1", "node_id": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["memory"]["state_name"] == "Ready" and body["memory"]["record_count"] == 2
    assert body["quality"]["not_logged"] == 3
    assert body["archived_total"] == 2 and body["generations"][0]["completeness_pct"] == 100.0
    assert body["transfers"][0]["received"] == 2 and body["transfers"][0]["progress_pct"] == 100.0
    assert body["recovery"]["recovered"] == 2          # no live uplinks were stored around these samples
    assert {m["key"] for m in body["metrics"]} >= {"flow_rate", "battery_voltage"}

    empty = supervisor.get("/api/v2/flash/analysis", params={"company": "Company_1", "node_id": 9})
    assert empty.status_code == 200 and empty.json()["memory"] is None


def test_recovery_uses_each_samples_own_interval():
    # A 50 s-interval sample 80 s from a live uplink is covered (±100 s); adding later 15 s-interval
    # samples must not shrink its window and reclassify it as gap fill.
    old = rec(3, 1, NOW - 9000, Transmission_rate=50000)
    live = [NOW - 9000 + 80]
    assert analyse({"memory": None, "transfers": []}, [old], live, NOW)["recovery"]["covered"] == 1
    newer = [rec(8, i, NOW - 600 + 10 * i, Transmission_rate=15000) for i in range(1, 6)]
    r = analyse({"memory": None, "transfers": []}, [old, *newer], live + [NOW - 590], NOW)["recovery"]
    assert r["tolerance_s"] == 60 and r["covered"] >= 1
    assert all(w["start"] != NOW - 9000 for w in r["recovered_windows"])
