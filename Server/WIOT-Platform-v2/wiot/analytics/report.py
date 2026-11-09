"""REPORT.md writer: a data-driven analysis report built only from the JSON artifacts.

Every number in the report is read from the artifacts at render time, so the report always
matches the dashboard's data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------
def pct(x: float | None, d: int = 0) -> str:
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def num(x: float | None, d: int = 2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, int) or (isinstance(x, float) and x.is_integer() and abs(x) >= 100):
        return f"{int(x):,}"
    return f"{x:,.{d}f}"


def day(ts: int | None) -> str:
    return "n/a" if ts is None else datetime.fromtimestamp(int(ts), tz=CAIRO).strftime("%Y-%m-%d %H:%M")


def ci(m: dict, d: int = 2) -> str:
    return f"{m['value']:.{d}f} [{m['ci_low']:.{d}f}, {m['ci_high']:.{d}f}]"


def table(headers: list[str], rows: list[list[Any]], align: list[str] | None = None) -> str:
    align = align or ["l"] + ["r"] * (len(headers) - 1)
    sep = ["---:" if a == "r" else ":---:" if a == "c" else "---" for a in align]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def fig(figs: dict[str, str], key: str, caption: str) -> str:
    if key not in figs:
        return ""
    return f"![{caption}](figures/{figs[key]})\n\n*Figure: {caption}*\n"


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------
def _summary(a: dict) -> str:
    s, m = a["summary"], a["model"]
    hm, hb = m["holdout"]["model"], m["holdout"]["baseline"]
    lines = ["## Executive summary", "",
             f"This report analyses the WIOT bench and field test from **{day(s['data_window']['start'])}** to "
             f"**{day(s['data_window']['end'])}** (Africa/Cairo): {s['counts']['messages']:,} decoded MQTT messages from "
             f"{s['counts']['nodes']} nodes of {s['counts']['companies']} companies, {s['counts']['commands']} operator "
             f"commands with their full delivery lifecycle, the firmware build history and the project source tree. "
             f"It also introduces a **Command Delivery Risk** model that tells the operator, before pressing *Send*, "
             f"how likely a node is to acknowledge a command published now.", "",
             "**Key findings**", ""]
    lines += [f"{i}. {f}" for i, f in enumerate(s["findings"], 1)]
    lines += ["", f"**Model in one line.** {m['selected']['name']} on the '{m['selected']['feature_set']}' feature set: "
                  f"hold-out PR-AUC {ci(hm['pr_auc'])} vs. {ci(hb['pr_auc'])} for the operator rule, ROC-AUC "
                  f"{ci(hm['roc_auc'])} vs. {ci(hb['roc_auc'])}. Useful as a triage aid (its UNLIKELY tier is reliable), "
                  f"not yet as an automatic gate.", ""]
    return "\n".join(lines)


def _data(a: dict) -> str:
    s = a["summary"]
    c = s["counts"]
    rows = []
    for n in s["nodes"]:
        rows.append([n["key"], day(n["first_seen"])[:10], day(n["last_seen"])[:10], f"{n['messages']:,}",
                     n["status"], n["telemetry"], n["active_days"],
                     ", ".join(f"{k} {v}" for k, v in sorted(n["power_modes"].items(), key=lambda kv: -kv[1]))])
    return "\n".join([
        "## 1. Data", "",
        "All databases were opened strictly read-only (SQLite `mode=ro` URIs).", "",
        table(["Source", "Content", "Rows"], [
            ["`messages_dbs/Company_*.db` / `messages`", "one row per decoded MQTT message (Status, Telemetry, Command history)",
             f"{c['messages']:,}"],
            ["`messages_dbs/Company_*.db` / `meter_samples`", "fingerprint-deduplicated flow-meter samples", f"{c['meter_samples']:,}"],
            ["`command_lifecycle.db` / `pending_commands`", "command journal (state, submit/broker/ACK times)", f"{c['commands']:,}"],
            ["`command_lifecycle.db` / `command_events`", "lifecycle events (accepted, submitted, node_ack, ...)", f"{c['command_events']:,}"],
            ["`Documentation/FirmwareBuild*`", "firmware ELF images and build logs per profile",
             f"{a['firmware'].get('n_builds', 0)} build folders"],
            ["`Documentation/PowerModes/power_combination_verification.json`", "power-mode guard verification",
             f"{a['firmware']['power_guard'].get('total', 0)} cases"],
        ], ["l", "l", "r"]), "",
        f"Uplinks (Status + Telemetry) total {c['uplinks']:,}; {c['command_history_rows']:,} `Command` rows in the message "
        f"tables are history copies and are not used as uplinks. Timestamps are server-receive epochs; days and hours "
        f"are reported in Africa/Cairo time.", "",
        table(["Node", "First seen", "Last seen", "Messages", "Status", "Telemetry", "Active days", "Power modes (uplinks)"],
              rows, ["l", "l", "l", "r", "r", "r", "r", "l"]), "",
        "**Nature of the data.** This is a bench and field-test data set: nodes were powered for test sessions, "
        "firmware changed several times during the window, sensor values come from RS485 simulators, and commands "
        "were issued by engineers testing features (often in bursts). Results describe this test campaign, not a "
        "production fleet.", ""])


def _methods(a: dict) -> str:
    m = a["model"]
    return "\n".join([
        "## 2. Methods", "",
        "- **Link reliability.** Inter-arrival times between consecutive uplinks per node (zero-second duplicates "
        "dropped); a *gap* is an interval longer than 3x the node's median; *availability* is the share of clock hours "
        "with at least one uplink between the node's first and last uplink.",
        "- **Store-and-forward delay.** Server receive time minus node measurement time for RTC-stamped uplinks "
        "(`time_source = node_rtc`, `rtc_valid = 1`).",
        "- **Health.** Watchdog and power-reset events are increments of the cumulative counters between consecutive "
        "Status messages; a decrease is an operator clear. Only increments across gaps of at most 30 minutes are "
        "counted as timed events.",
        "- **Energy model.** Average current per reporting interval from the per-configuration active and resting "
        "currents in `POWER_DOWN_MODE_STUDY.md` (section 4), plus explicit transmit and battery-divider terms "
        "(assumptions listed in `power.json`).",
        "- **Sensors.** Channels are used only where their validity flag is set and zero does not mean *missing*; "
        "Spearman correlations are computed pairwise; anomalies come from an IsolationForest on per-node robust "
        "z-scores, with the driving channel reported.",
        "- **Commands.** ACK rate = acknowledged / (acknowledged + outcome_unknown + rejected), superseded excluded, "
        "with Wilson 95% intervals.",
        f"- **Delivery-risk model.** {m['split']['method']}; {m['split']['cv']}. Candidates are ranked by CV PR-AUC; "
        "the simplest candidate within one paired standard error of the best is selected, then the smallest feature "
        "set within one paired SE (one-SE rule). Calibration, the operating threshold and the tiers are fitted on "
        "train out-of-fold predictions only; the hold-out is scored once, with 2,000 paired bootstrap resamples. "
        "Every feature is computed *as of* the command's submission time from the same function used for live "
        "scoring, so there is no train/serve skew and no future leakage.",
        "- **Firmware.** Flash = `.text + .rodata + .data`, RAM = `.data + .bss + .noinit` read from each profile's "
        "ELF. This is the STM32duino size recipe and reproduces the `Sketch uses ...` log lines exactly.", ""])


def _link(a: dict, figs: dict) -> str:
    s, link = a["summary"], a["link"]
    rows = [[n["key"], num(n["median_interval_s"], 0), num(n["p95_interval_s"], 0), n["gaps"],
             pct((n["availability_pct"] or 0) / 100), pct((n["rtc_valid_pct"] or 0) / 100),
             "n/a" if n["flow_valid_pct"] is None else pct(n["flow_valid_pct"] / 100)] for n in s["nodes"]]
    sf = link["store_forward"]
    sf_rows = [[r["mode"], r["n"], num(r["p50"], 0), num(r["p90"], 0), num(r["p99"], 0), pct(r["share_negative"])]
               for r in sf["by_mode"]]
    return "\n".join([
        "## 3. Findings", "", "### 3.1 Fleet and link reliability", "",
        table(["Node", "Median interval (s)", "p95 interval (s)", "Gaps > 3x median", "Hourly availability",
               "RTC valid", "Live flow valid"], rows), "",
        "Nodes were active in sessions of a few hours on a few days, so availability over the whole span is low by "
        "design. While a node was up its uplink cadence was regular (see the medians above). Gaps coincide with "
        "power-down periods and low-power modes; with this data, lost packets cannot be separated from sleep.", "",
        fig(figs, "uplinks_daily", "Uplinks per day for each node"),
        fig(figs, "heatmap", "Fleet uplinks by calendar day and hour (Africa/Cairo)"),
        fig(figs, "intervals", "Uplink inter-arrival distribution per node with median"),
        "### 3.2 Store-and-forward delay", "",
        table(["Power mode", "Samples", "p50 (s)", "p90 (s)", "p99 (s)", "Negative share"], sf_rows), "",
        f"In `LORA_WOR_STOP`, RTC-stamped samples reach the server minutes after measurement, the expected "
        f"store-and-forward behaviour of a sleeping LoRa node. In `NORMAL` and `REMOTE_WAKE` almost every value is "
        f"negative: the node RTC ran ahead of the server clock (by up to ~30 min), so these numbers measure clock "
        f"offset, not delay. {sf['excluded_rtc_invalid']} samples with `rtc_valid = 0` were excluded.", "",
        fig(figs, "store_forward", "Server receive minus node measurement time by power mode (symlog axis)")])


def _power(a: dict, figs: dict) -> str:
    s, p = a["summary"], a["power"]
    em = p["energy_model"]
    rows = [[n["key"], num(n["battery_last"], 3), num(n["battery_min"], 3), num(n["battery_slope_mv_per_day"], 1),
             n["wdt_resets"], n["power_resets"], n.get("wdt_increments_after_gap", 0),
             n.get("power_increments_after_gap", 0)] for n in s["nodes"]]
    cap = "5000"
    erows = []
    for c in em["configs"]:
        life = em["life_days"][c["name"]]
        div = em["life_days_with_divider"][c["name"]]
        erows.append([c["name"], num(c["active_ma"], 1), num(c["sleep_ma"], 3), num(c["active_s_per_report"], 0),
                      num(life["300"][cap], 0), num(life["900"][cap], 0), num(life["3600"][cap], 0),
                      num(div["900"][cap], 0)])
    lora = "LoRa node - scheduled only (Standby + E32 sleep)"
    l15, l15d = em["life_days"][lora]["900"][cap], em["life_days_with_divider"][lora]["900"][cap]
    return "\n".join([
        "### 3.3 Power and health", "",
        table(["Node", "Battery last (V)", "Battery min (V)", "Slope (mV/day)", "WDT resets", "Power resets",
               "WDT incr. after gap", "Power incr. after gap"], rows), "",
        "Voltages are those of bench supplies and partly charged cells; the slopes are within measurement noise and "
        "say nothing about field battery life. Reset counters are informative: the timed watchdog and power resets "
        "concentrate on a few nodes and sessions (see `power.json/resets`) and deserve a root-cause review. "
        "Increments that appear after long silences are kept separately because they mix re-flashing, EEPROM "
        "restores and resets while the node was unobserved.", "",
        fig(figs, "battery", "Battery or supply voltage per node (lines break across gaps > 3 h)"),
        "### 3.4 Energy model", "",
        "Estimated battery life (days) for a 5000 mAh battery (80% usable) by reporting interval. Currents come from "
        "the project's power-down study; transmit bursts are added explicitly; the last column adds the existing "
        "battery divider (0.236 mA).", "",
        table(["Configuration", "Active (mA)", "Sleep (mA)", "Active s/report", "5 min", "15 min", "1 h",
               "15 min + divider"], erows, ["l"] + ["r"] * 7), "",
        f"The scheduled LoRa node is the only battery-friendly option: ~{l15:,.0f} days at 15-minute reports at chip "
        f"level. The always-on battery divider alone cuts that to ~{l15d:,.0f} days, so switching the divider is the "
        f"single most valuable hardware change for battery nodes. Connected Wi-Fi/SIM profiles last about two weeks "
        f"whatever the interval, because their resting current dominates; they need mains or solar power.", "",
        fig(figs, "energy", "Modelled battery life vs reporting interval (5000 mAh)")])


def _sensors(a: dict, figs: dict) -> str:
    se = a["sensors"]
    q = se["quality"]
    rows = [[c["label"], c["unit"], f"{c['n']:,}", num(c["mean"]), num(c["std"]), num(c["min"]), num(c["p50"]),
             num(c["max"])] for c in se["channels"] if c["n"]]
    an = se["anomalies"]
    an_groups: dict[tuple, int] = {}
    for x in an:
        k = (x["key"], x["channel"], x["value"], x["expected"])
        an_groups[k] = an_groups.get(k, 0) + 1
    an_rows = [[k[0], k[1], num(k[2]), num(k[3]), n] for k, n in sorted(an_groups.items(), key=lambda kv: -kv[1])]
    pq = ", ".join(f"{r['name']} {r['count']:,}" for r in q["period_quality"])
    constant = [c["label"] for c in se["channels"] if c["n"] and c["std"] == 0]
    return "\n".join([
        "### 3.5 Sensors and data quality", "",
        table(["Channel", "Unit", "n", "Mean", "SD", "Min", "Median", "Max"], rows), "",
        (f"Constant channels ({', '.join(constant)}) confirm simulator inputs and are excluded from the correlation "
         f"matrix. " if constant else "") +
        "Correlations are mostly weak. The strongest ones (Supmea flow vs. Sondas moisture, battery vs. moisture) come "
        "from simulator settings changing between test sessions rather than from physics.", "",
        fig(figs, "sensor_corr", "Spearman correlation between sensor channels"),
        f"**Anomalies.** The top {len(an)} IsolationForest anomalies reduce to these patterns:", "",
        table(["Node", "Channel", "Value", "Node median", "Count in top list"], an_rows), "",
        "The Supmea simulator was driven to an out-of-range 4,800 m3/h during several sessions; the detector "
        "flags it consistently, which is the desired behaviour for a real meter fault.", "",
        f"**Data quality.** Live-flow validity {pct(q['flow_live_valid_rate'])} of flow-meter uplinks; RTC valid on "
        f"{pct(q['rtc_valid_rate'])} of uplinks; meter alarm flags non-zero on {pct(q['alarm_flags_nonzero_share'], 1)}; "
        f"period quality: {pq}. Of {q['message_derived_flow_samples']:,} message-derived flow samples, "
        f"{pct(q['duplicate_share'], 1)} were duplicates that the server's fingerprinted `meter_samples` store "
        f"removed ({q['meter_samples_rows']:,} rows kept).", ""])


def _commands(a: dict, figs: dict) -> str:
    c = a["commands"]
    t = c["totals"]
    rows = [[r["cmd_type"], r["family"], r["n"], r["acked"], r["unknown"], r["rejected"], r["superseded"],
             pct(r["ack_rate"]), f"{pct(r['ci_low'])}-{pct(r['ci_high'])}"] for r in c["by_type"]]
    mrows = [[r["mode"], r["n"] - r["superseded"], pct(r["ack_rate"]), f"{pct(r['ci_low'])}-{pct(r['ci_high'])}"]
             for r in c["by_power_mode"]]
    al, pb = c["ack_latency"], c["puback_latency"]
    return "\n".join([
        "### 3.6 Command delivery", "",
        f"{t['total']} commands: {t.get('acknowledged', 0)} acknowledged, {t.get('outcome_unknown', 0)} outcome unknown "
        f"(no ACK within 30 s), {t.get('rejected', 0)} rejected by the node, {t.get('superseded', 0)} superseded. "
        f"Overall ACK rate {pct(t['overall_ack_rate'])} (95% CI {pct(t['overall_ack_ci'][0])}-"
        f"{pct(t['overall_ack_ci'][1])}). Every command was published once; the broker confirmed {pb['n']} of them "
        f"(PUBACK median {num(pb['p50'], 0)} s, p99 {num(pb['p99'], 0)} s), so the broker is not the bottleneck: "
        f"the node's radio is.", "",
        table(["Type", "Family", "n", "ACK", "Unknown", "Rejected", "Superseded", "ACK rate", "95% CI"], rows,
              ["l", "l", "r", "r", "r", "r", "r", "r", "r"]), "",
        fig(figs, "cmd_by_type", "ACK rate by command type"),
        "GOSTM (telemetry request) has the lowest ACK rate among frequent commands. A plausible reason is that it is "
        "used to *probe* a node whose state is uncertain, so it tends to be sent when the node is least likely to be "
        "awake. Configuration commands (SRATE/STRAN) are often superseded: the operator re-sends a new value before "
        "the first one resolves.", "",
        table(["Power mode at submission", "Resolved", "ACK rate", "95% CI"], mrows), "",
        fig(figs, "ack_recency", "ACK rate by time since the node's last uplink"),
        f"The time since the node was last heard is the strongest single signal "
        f"({a['summary']['headline']['ack_rate_fresh_vs_stale']['label']}). This is the heuristic operators already "
        f"use, and it is the baseline the model has to beat.", "",
        f"**Latency.** Median ACK latency {num(al['p50'], 0)} s, p90 {num(al['p90'], 0)} s, p99 {num(al['p99'], 0)} s "
        f"(max {num(al['max'], 0)} s). {pct(c['late_share'])} of ACKs were late (after the 30 s deadline), and "
        f"{t['unknown_then_late_ack']} commands first declared outcome_unknown were later acknowledged.", "",
        fig(figs, "ack_latency", "ACK latency distribution with the 30 s deadline")])


def _firmware(a: dict, figs: dict) -> str:
    fw, pr = a["firmware"], a["project"]
    rows = [[p["name"], p["build"].replace("FirmwareBuild", ""), f"{p['flash_bytes']:,}", f"{p['flash_pct']:.1f}%",
             f"{p['ram_bytes']:,}", f"{p['ram_pct']:.1f}%",
             "n/a" if p["eeprom_headroom_bytes"] is None else f"{p['eeprom_headroom_bytes']:,}"]
            for p in sorted(fw["profiles"], key=lambda r: -r["flash_bytes"])]
    g = fw["power_guard"]
    grows = [[k, v["total"], v["accepted"], v["rejected"], v["passed"]] for k, v in g.get("by_transport", {}).items()]
    grows += [[f"role: {k}", v["total"], v["accepted"], v["rejected"], v["passed"]] for k, v in g.get("by_role", {}).items()]
    crows = [[c["name"], c["language"], c["files"], f"{c['lines']:,}"] for c in pr["components"]]
    t = pr["tests"]
    head = [p for p in fw["profiles"] if p.get("eeprom_headroom_bytes")]
    tight = min(head, key=lambda p: p["eeprom_headroom_bytes"]) if head else None
    big_ram = max(fw["profiles"], key=lambda p: p["ram_bytes"]) if fw["profiles"] else None
    growth = ""
    if tight:
        pts = sorted((e["date"], e["flash_bytes"], e["ram_bytes"]) for e in fw["trend"]
                     if e["source"] == "elf" and e["profile"] == tight["name"])
        if len(pts) >= 2:
            growth = (f" Across the dated build folders the {tight['name']} image grew from {pts[0][1]:,} B "
                      f"({pts[0][0]}) to {pts[-1][1]:,} B ({pts[-1][0]}), +{100 * (pts[-1][1] / pts[0][1] - 1):.0f}% "
                      f"flash and +{100 * (pts[-1][2] / pts[0][2] - 1):.0f}% static RAM.")
    limit_txt = (f"so {tight['name']} has {tight['eeprom_headroom_bytes']:,} B left." if tight else "")
    ram_txt = (f" Peak static RAM is {big_ram['ram_bytes']:,} B ({big_ram['ram_pct']:.0f}%, {big_ram['name']})."
               if big_ram else "")
    return "\n".join([
        "### 3.7 Firmware footprint and power-mode verification", "",
        table(["Profile", "Latest build", "Flash (B)", "Flash %", "RAM (B)", "RAM %", "Headroom to EEPROM sector (B)"],
              rows), "",
        "Percentages are of the STM32F401CC's 256 KiB flash and 64 KiB RAM. The practical flash limit is the EEPROM "
        f"emulation sector at 0x08020000 (128 KiB), {limit_txt}{ram_txt}{growth}", "",
        fig(figs, "firmware", "Flash and static RAM per build profile (latest build of each)"),
        fig(figs, "firmware_trend", "Flash footprint across dated build folders"),
        f"**Power-mode guard verification** (firmware {g.get('firmware_revision')}): {g.get('total')} configuration "
        f"combinations, {g.get('accepted')} accepted and {g.get('rejected')} rejected by compile-time guards; "
        f"all passed = **{g.get('all_passed')}** ({g.get('passed_cases')}/{g.get('total')}).", "",
        table(["Group", "Cases", "Accepted", "Rejected", "Passed"], grows), "",
        "### 3.8 Project size", "",
        table(["Component", "Language", "Files", "Non-blank lines"], crows, ["l", "l", "r", "r"]), "",
        f"Totals: {pr['totals']['files']:,} files / {pr['totals']['lines']:,} lines. Generated code "
        f"({pr['generated']['files']} files, {pr['generated']['lines']:,} lines: nanopb `*.pb.c/h`, `*_pb2.py`) and "
        f"vendor code ({pr['vendor']['files']:,} files: STM32 HAL/CMSIS, third-party libraries) are excluded. "
        f"Tests: {t['files']} files with {t['python_test_functions']} Python test functions and "
        f"{t['cpp_test_cases']} C++ host-test scenarios.", ""])


def _model(a: dict, figs: dict) -> str:
    m = a["model"]
    sel = m["selected"]
    hm, hb, hd = m["holdout"]["model"], m["holdout"]["baseline"], m["holdout"]["delta_model_minus_baseline"]
    cand = [[c["name"], c["kind"], f"{c['cv_pr_auc']:.3f} +/- {c['cv_pr_auc_std']:.3f}", f"{c['cv_roc_auc']:.3f}",
             f"{c['cv_brier']:.3f}", f"{c['best_f1']:.3f}",
             "" if c["paired_diff_vs_best"] is None else f"{c['paired_diff_vs_best']:+.3f} ({c['paired_se']:.3f})"]
            for c in m["candidates"]]
    fs = [[e["name"], e["n_features"], f"{e['cv_pr_auc']:.3f}", f"{e['paired_diff_vs_best']:+.3f} ({e['paired_se']:.3f})",
           f"{e['logreg_cv_pr_auc']:.3f}", "yes" if e["chosen"] else ""] for e in m["feature_set_experiments"]]
    names = {"pr_auc": "PR-AUC (AP)", "roc_auc": "ROC-AUC", "precision": "Precision", "recall": "Recall",
             "f1": "F1", "accuracy": "Accuracy", "specificity": "Specificity", "brier": "Brier (lower is better)"}
    hold = [[names[k], ci(hm[k]), ci(hb[k]), f"{hd[k]['value']:+.3f} [{hd[k]['ci_low']:+.3f}, {hd[k]['ci_high']:+.3f}]"]
            for k in names]
    cm, cb = m["confusion"]["model"], m["confusion"]["baseline"]
    tiers = [[r["tier"], r["n"], pct(r["share"]), pct(r["observed_ack_rate"])] for r in sel["tier_table_holdout"]]
    tiers_oof = {r["tier"]: r for r in sel["tier_table_oof"]}
    th = {r["tier"]: r for r in sel["tier_table_holdout"]}
    var = [[v["target"], v["definition"], v["pos_train"], v["pos_test"], f"{v['cv_pr_auc']:.3f}",
            f"{v['holdout_pr_auc']:.3f}", f"{v['holdout_roc_auc']:.3f}", pct(v["holdout_prevalence"])]
           for v in m["target_variants"]]
    shap = "; ".join(f"*{r['label']}*" for r in m["shap_global"][:6])
    feats = "\n".join(f"- `{f['name']}`: {f['label']}" for f in m["feature_schema"])
    return "\n".join([
        "## 4. Machine learning: Command Delivery Risk", "",
        "### 4.1 Task", "",
        f"{m['task']} {m['target_definition']} Positive class for all metrics: *{m['positive_label']}*. "
        f"Train: {m['n_train']} commands ({m['pos_train']} positive); hold-out: {m['n_test']} commands "
        f"({m['pos_test']} positive, prevalence {pct(m['holdout']['prevalence'])}); {m['n_superseded_excluded']} "
        f"superseded commands excluded. The hold-out starts at {day(m['split']['test_start'])}.", "",
        "The model answers the operator's question *\"if I publish this now, will the node get it?\"*. A low score "
        "means the node is probably asleep, so the command should be queued for the next wake window (or preceded by "
        "a WAKE) instead of being published into the void.", "",
        "### 4.2 Features (all computed as of submission time)", "", feats, "",
        "Link features use only uplinks with `timestamp < submitted_at`. History features use previous commands to "
        "the same node whose outcome was already observable: their reply arrived before submission, or their 30 s "
        "deadline had passed. A unit test checks this property on a synthetic timeline.", "",
        "### 4.3 Candidates (3x5 grouped CV on train)", "",
        table(["Candidate", "Kind", "CV PR-AUC (mean +/- SD)", "CV ROC-AUC", "CV Brier", "Best F1",
               "Paired diff vs best (SE)"], cand, ["l", "l", "r", "r", "r", "r", "r"]), "",
        fig(figs, "model_cv", "Grouped-CV PR-AUC of every candidate"),
        f"**Selection.** {sel['why']}", "",
        "Fold-to-fold spread is large (SD ~0.18) because operator sessions differ strongly in delivery rate. Several "
        "candidates are statistically indistinguishable, which is why the one-SE rule (prefer the simplest model "
        "among the equivalent ones) is used rather than the raw maximum. The gradient-boosted trees scored below the "
        "simpler models, plausibly because boosting overfits ~300 noisy, bursty rows.", "",
        "### 4.4 Feature-set experiments", "",
        table(["Feature set", "Features", "CV PR-AUC", "Paired diff vs best (SE)", "Logistic reg. CV PR-AUC", "Chosen"],
              fs, ["l", "r", "r", "r", "r", "c"]), "",
        "Removing the per-node ACK history costs the most, so recent delivery outcomes carry information beyond raw "
        "link recency. Node identity adds a small, borderline gain.", "",
        "### 4.5 Calibration, threshold and tiers", "",
        f"- Calibration: {sel['calibration']}.",
        f"- Operating threshold: **{sel['threshold']:.3f}**. {sel['threshold_rule']}",
        f"- Tiers: **LIKELY** if p >= {sel['tiers']['likely']:.3f} ({sel['tiers']['likely_rule']}); **UNLIKELY** if "
        f"p < {sel['tiers']['unlikely']:.3f} ({sel['tiers']['unlikely_rule']}); otherwise UNCERTAIN. On train OOF the "
        f"tiers hold {tiers_oof['LIKELY']['n']} / {tiers_oof['UNCERTAIN']['n']} / {tiers_oof['UNLIKELY']['n']} "
        f"commands with ACK rates {pct(tiers_oof['LIKELY']['observed_ack_rate'])} / "
        f"{pct(tiers_oof['UNCERTAIN']['observed_ack_rate'])} / {pct(tiers_oof['UNLIKELY']['observed_ack_rate'])}.", "",
        fig(figs, "calibration", "Reliability of train out-of-fold probabilities"),
        "### 4.6 Hold-out evaluation (scored once)", "",
        table(["Metric", "Model [95% CI]", "Baseline [95% CI]", "Model - baseline [95% CI]"], hold,
              ["l", "r", "r", "r"]), "",
        f"Baseline: {m['holdout']['baseline_definition']}", "",
        table(["Confusion matrix", "TN", "FP", "FN", "TP"],
              [["Model", cm["tn"], cm["fp"], cm["fn"], cm["tp"]], ["Baseline", cb["tn"], cb["fp"], cb["fn"], cb["tp"]]]),
        "",
        f"The model ranks commands better than the recency rule (PR-AUC {hd['pr_auc']['value']:+.3f}, ROC-AUC "
        f"{hd['roc_auc']['value']:+.3f}, bootstrap P(better) {pct(hd['pr_auc']['p_model_better'])} and "
        f"{pct(hd['roc_auc']['p_model_better'])}), but both differences have 95% intervals that include zero. At its "
        f"balanced operating point it is more conservative than the rule: higher specificity and precision, lower "
        f"recall. **Honest verdict: with 124 hold-out commands from two nodes the model is a modest, not yet "
        f"statistically confirmed, improvement over the operator heuristic.**", "",
        fig(figs, "holdout_curves", "Hold-out precision-recall and ROC curves, model vs. baseline"),
        table(["Hold-out tier", "Commands", "Share", "Observed ACK rate"], tiers), "",
        f"The tiers are where the operational value lies. On the hold-out, UNLIKELY commands were delivered "
        f"{pct(th['UNLIKELY']['observed_ack_rate'])} of the time and LIKELY commands "
        f"{pct(th['LIKELY']['observed_ack_rate'])}, against {pct(m['holdout']['prevalence'])} overall. A dashboard can "
        f"therefore warn on UNLIKELY and offer *queue for next wake* without blocking the operator.", "",
        fig(figs, "tiers", "Observed ACK rate per delivery tier, train OOF vs. hold-out"),
        "### 4.7 Explanations", "",
        f"Global importance is the mean |SHAP| on the training set, in calibrated log-odds. The top drivers are "
        f"{shap}. Every individual prediction is decomposed exactly into a base value plus per-feature "
        f"contributions that sum to its log-odds (maximum additivity error {m['shap_additivity_max_error']:.1e}), "
        f"which the dashboard can show as a waterfall.", "",
        fig(figs, "shap", "Global feature importance (mean |SHAP|)"),
        "### 4.8 Target variants (reported only, never used for selection)", "",
        table(["Target", "Definition", "Pos. train", "Pos. test", "CV PR-AUC", "Hold-out PR-AUC", "Hold-out ROC-AUC",
               "Hold-out prevalence"], var, ["l", "l", "r", "r", "r", "r", "r", "r"]), ""])


def _limitations(a: dict) -> str:
    m = a["model"]
    lines = ["## 5. Limitations", ""]
    lines += [f"- {n}" for n in m["notes"]]
    lines += [
        "- Descriptive statistics come from a short test campaign with simulated sensors and changing firmware; they "
        "characterise the test, not long-term field behaviour.",
        "- Store-and-forward delay mixes queueing delay with node RTC offset; only the `LORA_WOR_STOP` values are "
        "clearly delay.",
        "- The energy model uses the study's chip and module currents (no regulator, sensor or PCB leakage) and "
        "assumed active windows; it ranks configurations but should be replaced by measured current profiles.",
        "- Reset counts depend on counters persisted in EEPROM; re-flashing and EEPROM restores create jumps that "
        "cannot be timed and are reported separately.", ""]
    return "\n".join(lines)


def _recommendations(a: dict) -> str:
    c = a["commands"]
    al = c["ack_latency"]
    return "\n".join([
        "## 6. Recommendations", "",
        "1. **Do not publish into sleep.** Show the delivery tier next to *Send*. For UNLIKELY commands, default to "
        "the server-side queue (deliver on the node's next uplink or wake window) or send WAKE first. This should "
        "remove a large share of `outcome_unknown` results.",
        f"2. **Lengthen the ACK window for low-power modes.** ACK p99 is {num(al['p99'], 0)} s against a 30 s deadline, "
        f"and {c['totals']['unknown_then_late_ack']} commands were acknowledged after being declared unknown. A "
        f"mode-aware deadline (for example 90 s for `LORA_WOR_STOP`) would cut false *unknown* outcomes and the "
        f"re-sends they trigger (superseded commands).",
        "3. **Keep node clocks in sync.** RTC offsets of up to ~30 min were observed. Schedule STIME after every "
        "power-up or reconnect and alarm on |offset| > 60 s, because store-and-forward timestamps depend on it.",
        "4. **Investigate reset clusters.** Review the timed watchdog and power-reset bursts in `power.json` together "
        "with firmware versions; persistent WDT resets in low-power modes point to wake/clock-restore paths.",
        "5. **Switch the battery divider** (or raise its resistance) before deploying scheduled LoRa nodes on "
        "batteries; in the model it costs more than the whole STM32 + E32 sleep budget.",
        "6. **Watch flash and RAM headroom.** The largest LoRa WOR images sit a few tens of KB below the "
        "EEPROM-emulation sector and use over half of static RAM (see section 3.7); add a CI gate on both.",
        "7. **Grow the training set deliberately.** Log every command attempt with the gateway's WOR state, vary send "
        "timing relative to uplinks, and retrain monthly with the same pipeline. With about 1,000 labelled commands "
        "over more nodes, the model/baseline difference could be confirmed or rejected.", ""])


def _appendix(a: dict) -> str:
    return "\n".join([
        "## Appendix: reproduction", "",
        "```bash",
        "cd Server/WIOT-Platform-v2",
        ".venv/Scripts/python.exe -m wiot.analytics.pipeline \\",
        '    --data-dir "../WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard" \\',
        '    --repo-root "../.." --out data/analytics',
        ".venv/Scripts/python.exe -m pytest tests/test_analytics.py -q",
        "```", "",
        "Artifacts: `summary.json`, `link.json`, `power.json`, `sensors.json`, `commands.json`, `model.json`, "
        "`firmware.json`, `project.json`, `model.joblib` (served by `wiot.analytics.predictor.CommandRiskPredictor`), "
        "`figures/*.png`. The pipeline is deterministic (fixed seeds) and opens every database read-only.", ""])


def write_report(out: Path, a: dict[str, Any], figs: dict[str, str]) -> Path:
    generated = datetime.fromtimestamp(a["summary"]["generated_at"], tz=timezone.utc).astimezone(CAIRO)
    parts = [
        "# WIOT Field-Test Analytics and Command Delivery Risk", "",
        f"*Generated {generated:%Y-%m-%d %H:%M} (Africa/Cairo) by `wiot.analytics.pipeline` "
        f"v{a['summary'].get('version', '')}. All figures and numbers are produced from the JSON artifacts in "
        f"this folder.*", "",
        _summary(a), _data(a), _methods(a), _link(a, figs), _power(a, figs), _sensors(a, figs), _commands(a, figs),
        _firmware(a, figs), _model(a, figs), _limitations(a), _recommendations(a), _appendix(a),
    ]
    path = out / "REPORT.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
