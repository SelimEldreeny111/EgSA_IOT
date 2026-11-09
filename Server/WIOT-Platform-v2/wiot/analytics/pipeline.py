"""WIOT analytics pipeline CLI.

    python -m wiot.analytics.pipeline --data-dir <server data dir> --repo-root <project root> --out <dir>

Reads the SQLite databases read-only, runs the descriptive analyses and the "Command Delivery
Risk" model, and writes ``summary.json``, ``link.json``, ``power.json``, ``sensors.json``,
``commands.json``, ``model.json``, ``firmware.json``, ``project.json``, ``model.joblib``,
``figures/*.png`` and ``REPORT.md`` into ``--out``. Deterministic (fixed seeds).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import dataset as ds
from . import descriptive, energy, modeling, repo_stats
from .common import write_json

VERSION = "1.0.0"
ARTIFACTS = ["summary", "link", "power", "sensors", "commands", "model", "firmware", "project"]


def _log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Summary, findings and model notes
# ---------------------------------------------------------------------------
def build_nodes(fleet: list[dict], power_nodes: dict[str, dict]) -> list[dict]:
    keys = ["company", "region", "node_id", "first_seen", "last_seen", "messages", "status", "telemetry",
            "availability_pct", "median_interval_s", "p95_interval_s", "gaps", "rtc_valid_pct", "flow_valid_pct"]
    out = []
    for n in fleet:
        p = power_nodes.get(n["key"], {})
        rec = {k: n.get(k) for k in keys}
        rec.update({"key": n["key"], "command_history_rows": n["command_history_rows"], "active_days": n["active_days"],
                    "longest_gap_s": n["longest_gap_s"], "battery_last": p.get("battery_last"),
                    "battery_min": p.get("battery_min"), "battery_slope_mv_per_day": p.get("battery_slope_mv_per_day"),
                    "wdt_resets": p.get("wdt_resets"), "power_resets": p.get("power_resets"),
                    "wdt_increments_after_gap": p.get("wdt_increments_after_gap"),
                    "power_increments_after_gap": p.get("power_increments_after_gap"),
                    "power_modes": p.get("power_modes", {})})
        out.append(rec)
    return out


def _metric(model: dict, who: str, key: str) -> dict:
    return model["holdout"][who][key]


def headline(model: dict, commands: dict, nodes: list[dict], firmware: dict, power: dict, msgs_n: int) -> dict:
    tot = commands["totals"]
    rec = {r["bin_low_s"]: r for r in commands["by_recency"]}
    fresh = [r for r in commands["by_recency"] if r["bin_high_s"] <= 30]
    stale = [r for r in commands["by_recency"] if r["bin_low_s"] >= 120]
    fresh_rate = sum(r["acked"] for r in fresh) / max(1, sum(r["acked"] + r["unknown"] + r["rejected"] for r in fresh))
    stale_rate = sum(r["acked"] for r in stale) / max(1, sum(r["acked"] + r["unknown"] + r["rejected"] for r in stale))
    guard = firmware["power_guard"]
    max_flash = max(firmware["profiles"], key=lambda r: r["flash_pct"]) if firmware["profiles"] else None
    lora_life = power["energy_model"]["life_days"]["LoRa node - scheduled only (Standby + E32 sleep)"]["900"]["5000"]
    del rec
    return {
        "messages": {"value": msgs_n, "label": "Decoded MQTT messages analysed", "unit": "messages"},
        "nodes": {"value": len(nodes), "label": "Nodes (2 companies)", "unit": "nodes"},
        "command_ack_rate": {"value": tot["overall_ack_rate"], "label": "Commands acknowledged (non-superseded)",
                             "unit": "share", "ci": tot["overall_ack_ci"]},
        "ack_rate_fresh_vs_stale": {"value": fresh_rate - stale_rate,
                                    "label": f"ACK-rate gap: node heard <= 30 s ago ({fresh_rate:.0%}) vs >= 2 min ago "
                                             f"({stale_rate:.0%})", "unit": "share points"},
        "ack_latency_p50": {"value": commands["ack_latency"]["p50"], "label": "Median ACK latency", "unit": "s"},
        "model_pr_auc": {"value": _metric(model, "model", "pr_auc")["value"],
                         "label": f"Delivery-risk model hold-out PR-AUC (baseline "
                                  f"{_metric(model, 'baseline', 'pr_auc')['value']:.2f})", "unit": "AP",
                         "ci": [_metric(model, "model", "pr_auc")["ci_low"], _metric(model, "model", "pr_auc")["ci_high"]]},
        "model_roc_auc": {"value": _metric(model, "model", "roc_auc")["value"],
                          "label": f"Hold-out ROC-AUC (baseline {_metric(model, 'baseline', 'roc_auc')['value']:.2f})",
                          "unit": "AUC"},
        "power_guard": {"value": guard.get("passed_cases"), "label": f"Power-mode guard cases passed of {guard.get('total')}",
                        "unit": "cases"},
        "max_flash_pct": {"value": max_flash["flash_pct"] if max_flash else None,
                          "label": f"Largest firmware image ({max_flash['name'] if max_flash else '-'}) of 256 KiB flash",
                          "unit": "%"},
        "lora_battery_days": {"value": lora_life, "label": "Model battery life, LoRa scheduled node, 15-min reports, "
                                                           "5000 mAh (chip-level)", "unit": "days"},
    }


def findings(model: dict, commands: dict, nodes: list[dict], link: dict, power: dict, firmware: dict,
             sensors: dict) -> list[str]:
    tot = commands["totals"]
    out = []
    labelled = tot["labelled"]
    out.append(f"{tot['total']} commands were submitted; {tot.get('superseded', 0)} were superseded by a newer operator "
               f"intent. Of the {labelled} that resolved, {tot.get('acknowledged', 0)} "
               f"({tot['overall_ack_rate']:.0%}, 95% CI {tot['overall_ack_ci'][0]:.0%}-{tot['overall_ack_ci'][1]:.0%}) "
               f"were acknowledged and {tot.get('outcome_unknown', 0)} timed out with no ACK - mostly commands published "
               f"while the node's radio was asleep.")
    fresh = [r for r in commands["by_recency"] if r["bin_high_s"] <= 10]
    stale = [r for r in commands["by_recency"] if r["bin_low_s"] >= 3600]
    if fresh and stale:
        out.append(f"Delivery depends on how recently the node was heard: {fresh[0]['ack_rate']:.0%} of commands sent "
                   f"within 10 s of an uplink were acknowledged versus {stale[0]['ack_rate']:.0%} when the last uplink "
                   f"was more than an hour old.")
    lat = commands["ack_latency"]
    out.append(f"When a node does answer it is fast: median ACK latency {lat['p50']:.0f} s, p90 {lat['p90']:.0f} s; "
               f"{commands['late_share']:.0%} of ACKs arrived after the 30 s deadline (late) and "
               f"{tot['unknown_then_late_ack']} commands first marked outcome_unknown were later acknowledged.")
    hm, hb = model["holdout"]["model"], model["holdout"]["baseline"]
    d = model["holdout"]["delta_model_minus_baseline"]["pr_auc"]
    verdict = ("a modest gain whose 95% CI includes zero" if d["ci_low"] <= 0 else "a gain whose 95% CI excludes zero")
    out.append(f"The delivery-risk model ({model['selected']['name']}, features '{model['selected']['feature_set']}') "
               f"reaches hold-out PR-AUC {hm['pr_auc']['value']:.2f} (95% CI {hm['pr_auc']['ci_low']:.2f}-"
               f"{hm['pr_auc']['ci_high']:.2f}) and ROC-AUC {hm['roc_auc']['value']:.2f} versus "
               f"{hb['pr_auc']['value']:.2f} / {hb['roc_auc']['value']:.2f} for the operator's 'heard recently' rule - "
               f"{verdict} (delta PR-AUC {d['value']:+.2f}, CI {d['ci_low']:+.2f} to {d['ci_high']:+.2f}).")
    ul = next((r for r in model["selected"]["tier_table_holdout"] if r["tier"] == "UNLIKELY"), None)
    if ul and ul["n"]:
        out.append(f"Operationally the useful output is the UNLIKELY tier: on the hold-out it flagged {ul['n']} commands "
                   f"({ul['share']:.0%}) of which only {ul['observed_ack_rate']:.0%} were delivered - these are the "
                   f"commands to queue for the node's next wake window instead of publishing now.")
    avail = [n["availability_pct"] for n in nodes if n["availability_pct"] is not None]
    meds = [n["median_interval_s"] for n in nodes if n["median_interval_s"]]
    out.append(f"Links were intermittent by design (bench/field test, nodes powered for sessions): hourly availability "
               f"between first and last contact ranged {min(avail):.0f}-{max(avail):.0f}% per node, with median uplink "
               f"intervals of {min(meds):.0f}-{max(meds):.0f} s while active.")
    sf = {r["mode"]: r for r in link["store_forward"]["by_mode"]}
    if "LORA_WOR_STOP" in sf:
        r = sf["LORA_WOR_STOP"]
        out.append(f"Store-and-forward is visible in LORA_WOR_STOP mode: RTC-stamped samples reached the server a median "
                   f"{r['p50']:.0f} s (p99 {r['p99']:.0f} s) after measurement; in NORMAL/REMOTE_WAKE modes the "
                   f"difference is dominated by node RTC offset (negative medians), so RTC sync (STIME) matters.")
    resets = sum((n["wdt_resets"] or 0) for n in nodes), sum((n["power_resets"] or 0) for n in nodes)
    worst = max(nodes, key=lambda n: (n["wdt_resets"] or 0) + (n["power_resets"] or 0))
    out.append(f"Health counters show {resets[0]} watchdog and {resets[1]} power resets that can be timed (counter "
               f"increments between Status messages <= 30 min apart), led by {worst['key']} "
               f"({worst['wdt_resets']} WDT / {worst['power_resets']} power); larger jumps after long silences "
               f"(re-flash, power-off) are reported separately and not counted.")
    if firmware["profiles"]:
        big = max(firmware["profiles"], key=lambda r: r["flash_bytes"])
        bigram = max(firmware["profiles"], key=lambda r: r["ram_bytes"])
        head = [p for p in firmware["profiles"] if p.get("eeprom_headroom_bytes")]
        tight = min(head, key=lambda p: p["eeprom_headroom_bytes"]) if head else None
        msg = (f"Firmware: the largest image is {big['name']} at {big['flash_bytes']:,} B ({big['flash_pct']:.0f}% of "
               f"256 KiB) and peak static RAM is {bigram['ram_bytes']:,} B ({bigram['ram_pct']:.0f}%, {bigram['name']})")
        if tight:
            msg += (f"; {tight['name']} leaves {tight['eeprom_headroom_bytes']:,} B before the EEPROM-emulation sector, "
                    f"the real limit")
        g = firmware["power_guard"]
        msg += f". All {g.get('total')} power-mode guard combinations passed ({g.get('accepted')} accepted, {g.get('rejected')} rejected by design)."
        out.append(msg)
    q = sensors["quality"]
    out.append(f"Data quality: live-flow validity {q['flow_live_valid_rate']:.0%} of flow-meter uplinks, RTC validity "
               f"{q['rtc_valid_rate']:.0%} of uplinks, {q['alarm_flags_nonzero_share']:.0%} with meter alarm flags, and "
               f"{q['duplicate_share']:.0%} of message-derived flow samples were duplicates removed by the server's "
               f"fingerprint store. Sensor values come from RS485 simulators on the bench (HNDA channels are constant), "
               f"so anomalies reflect simulator reconfiguration rather than field events.")
    return out[:10]


def holdout_nodes_note(model: dict) -> str:
    per = model["holdout"]["per_node"]
    low = min(per, key=lambda r: r["ack_rate"])
    return (f"The hold-out period contains {len(per)} node(s) ({', '.join(r['node_key'] for r in per)}) and a delivery "
            f"prevalence of {model['holdout']['prevalence']:.0%} vs {model['pos_train'] / model['n_train']:.0%} in train; "
            f"{low['node_key']} acknowledged only {low['ack_rate']:.0%} of its {low['n']} hold-out commands, so results "
            f"may not transfer to other nodes or periods.")


def model_notes(model: dict) -> list[str]:
    hm = model["holdout"]["model"]
    d = model["holdout"]["delta_model_minus_baseline"]
    sel = model["selected"]
    notes = [
        f"Small data: {model['n_train']} training and {model['n_test']} hold-out commands from 5 nodes over ~1 month; "
        f"CIs are wide (hold-out PR-AUC {hm['pr_auc']['ci_low']:.2f}-{hm['pr_auc']['ci_high']:.2f}).",
        f"The model is better than the operator rule at ranking (delta PR-AUC {d['pr_auc']['value']:+.2f}, "
        f"P(model better) {d['pr_auc']['p_model_better']:.0%} over bootstrap resamples; delta ROC-AUC "
        f"{d['roc_auc']['value']:+.2f}); the 95% bootstrap CI of the PR-AUC difference "
        f"({d['pr_auc']['ci_low']:+.2f} to {d['pr_auc']['ci_high']:+.2f}) "
        f"{'includes' if d['pr_auc']['ci_low'] <= 0 else 'excludes'} zero, so the gain is "
        f"{'not ' if d['pr_auc']['ci_low'] <= 0 else ''}statistically significant at 95%.",
        holdout_nodes_note(model),
        "Bootstrap CIs resample commands independently; commands come in operator bursts, so true uncertainty is larger.",
        f"Operating threshold = Youden's J on train OOF probabilities ({sel['threshold']:.2f}). The max-F1 threshold "
        f"({sel['f1_threshold_reference']:.2f}) was rejected because it approaches 'predict delivered for everything'; "
        f"its hold-out metrics are kept in selected.holdout_at_f1_threshold_reference. For operations the tiers matter "
        f"more than the single threshold.",
        f"Calibration: {sel['calibration']}.",
        (f"Feature set '{sel['feature_set']}' was kept by the one-SE rule. " + (
            "It includes node identity (node_key, company): an unseen node gets all-zero identity columns, i.e. the "
            "fleet-average effect, so scores for brand-new nodes rely on the link/history features only."
            if sel["feature_set"] in ("all", "no_ack_history") else
            "Node identity was dropped, so the model generalises to new nodes.")
         + " Battery voltage and cumulative reset counters are partial node proxies."),
        "Grouped CV inside train is not time-ordered (a fold may train on later sessions); the temporal hold-out is the "
        "honest estimate. Candidate hyper-parameters are fixed (not tuned) to avoid selection bias with n ~ 300.",
        "Target counts 'rejected' (node replied with failure) as not delivered, per the brief; the 'any reply' variant "
        "is reported in target_variants and behaves the same.",
        "Commands were sent only during working hours (09-16 Cairo), so hour_local carries little information and the "
        "model has not seen night-time behaviour.",
    ]
    return notes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(data_dir: Path, repo_root: Path, out: Path, figures: bool = True) -> dict[str, Any]:
    t0 = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    _log(f"[1/7] loading databases (read-only) from {data_dir}")
    msgs = ds.load_messages(data_dir)
    cmds = ds.load_commands(data_dir)
    events = ds.load_command_events(data_dir)
    meter = ds.load_meter_samples(data_dir)
    _log(f"      {len(msgs)} messages, {len(cmds)} commands, {len(events)} events, {len(meter)} meter samples")

    _log("[2/7] building command features (as-of submission time)")
    X_all = ds.command_features(cmds, msgs, history=cmds)

    _log("[3/7] descriptive analyses")
    fleet, link = descriptive.fleet_and_link(msgs)
    power_nodes, power = descriptive.power_health(msgs)
    power["energy_model"] = energy.energy_model()
    sensors = descriptive.sensors_analysis(msgs, meter)
    commands = descriptive.commands_analysis(cmds, events, X_all)

    _log("[4/7] training and evaluating the delivery-risk model")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        training = modeling.train_and_evaluate(X_all, cmds, log=_log)
    model = training.model_json
    model["notes"] = model_notes(model)

    _log("[5/7] firmware, power-guard and project statistics")
    firmware = repo_stats.firmware_stats(repo_root)
    firmware["power_guard"] = repo_stats.power_guard_stats(repo_root)
    project = repo_stats.project_stats(repo_root, exclude=(out,))

    nodes = build_nodes(fleet, power_nodes)
    up = msgs[msgs["is_uplink"]]
    summary = {
        "generated_at": int(time.time()), "version": VERSION,
        "data_window": {"start": int(msgs["timestamp"].min()), "end": int(msgs["timestamp"].max())},
        "counts": {"messages": int(len(msgs)), "status": int((msgs["type"] == "Status").sum()),
                   "telemetry": int((msgs["type"] == "Telemetry").sum()),
                   "command_history_rows": int((msgs["type"] == "Command").sum()),
                   "meter_samples": int(len(meter)), "commands": int(len(cmds)), "command_events": int(len(events)),
                   "companies": int(msgs["company"].nunique()), "nodes": int(msgs["node_key"].nunique()),
                   "uplinks": int(len(up))},
        "headline": headline(model, commands, nodes, firmware, power, len(msgs)),
        "nodes": nodes,
        "findings": findings(model, commands, nodes, link, power, firmware, sensors),
        "sources": {"data_dir": str(data_dir), "repo_root": str(repo_root)},
    }
    artifacts = {"summary": summary, "link": link, "power": power, "sensors": sensors, "commands": commands,
                 "model": model, "firmware": firmware, "project": project}
    _log(f"[6/7] writing artifacts to {out}")
    for name in ARTIFACTS:
        write_json(out / f"{name}.json", artifacts[name])
    import joblib

    bundle = {"model": training.model, "model_name": model["selected"]["name"],
              "threshold": training.extras["threshold"], "tiers": training.extras["tiers"],
              "feature_schema": model["feature_schema"], "labels": ds.FEATURE_LABELS, "cmd_family": ds.CMD_FAMILY,
              "trained_at": summary["generated_at"], "version": VERSION, "data_dir": str(data_dir),
              "selected": {k: model["selected"][k] for k in ("name", "members", "feature_set", "features")}}
    joblib.dump(bundle, out / "model.joblib", compress=3)

    figs: dict[str, str] = {}
    if figures:
        _log("[7/7] figures and REPORT.md")
        from . import figures as fig_mod, report

        # figures and report are rendered from the written JSON, exactly what the dashboard consumes
        loaded = {k: json.loads((out / f"{k}.json").read_text("utf-8")) for k in ARTIFACTS}
        figs = fig_mod.render_all(loaded, out / "figures")
        report.write_report(out, loaded, figs)
    elapsed = time.perf_counter() - t0
    _print_summary(artifacts, elapsed, out)
    return {"artifacts": artifacts, "figures": figs, "elapsed_s": elapsed}


def _print_summary(a: dict, elapsed: float, out: Path) -> None:
    m = a["model"]
    hm, hb = m["holdout"]["model"], m["holdout"]["baseline"]
    _log("")
    _log("=== WIOT analytics summary ===")
    _log(f"window {datetime.fromtimestamp(a['summary']['data_window']['start'], tz=timezone.utc):%Y-%m-%d} -> "
         f"{datetime.fromtimestamp(a['summary']['data_window']['end'], tz=timezone.utc):%Y-%m-%d}; "
         f"{a['summary']['counts']['messages']} messages, {a['summary']['counts']['commands']} commands")
    _log(f"selected model: {m['selected']['name']} [{m['selected']['feature_set']}], threshold "
         f"{m['selected']['threshold']:.3f}, tiers {m['selected']['tiers']['unlikely']:.2f}/{m['selected']['tiers']['likely']:.2f}")
    for k in ("pr_auc", "roc_auc", "f1", "brier"):
        _log(f"  hold-out {k:8s} model {hm[k]['value']:.3f} [{hm[k]['ci_low']:.3f}, {hm[k]['ci_high']:.3f}]   "
             f"baseline {hb[k]['value']:.3f} [{hb[k]['ci_low']:.3f}, {hb[k]['ci_high']:.3f}]")
    _log("  top SHAP: " + ", ".join(f"{r['feature']} ({r['mean_abs_shap']:.2f})" for r in m["shap_global"][:5]))
    _log(f"artifacts in {out}  ({elapsed:.1f} s)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wiot.analytics.pipeline", description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", required=True, type=Path, help="folder with messages_dbs/ and command_lifecycle.db")
    ap.add_argument("--repo-root", required=True, type=Path, help="project root (Documentation/, Node/, ...)")
    ap.add_argument("--out", required=True, type=Path, help="output folder for the artifacts")
    ap.add_argument("--no-figures", action="store_true", help="skip figures and REPORT.md")
    args = ap.parse_args(argv)
    np.random.seed(modeling.SEED)
    run(args.data_dir.resolve(), args.repo_root.resolve(), args.out.resolve(), figures=not args.no_figures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
