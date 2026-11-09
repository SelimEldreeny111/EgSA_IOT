"""Matplotlib figures for REPORT.md, rendered from the JSON artifacts (dark surface #0b1220).

Colours: categorical slots from the validated dark palette (checked against #0b1220 for
lightness band, chroma, CVD separation and contrast); sequential = one blue hue; diverging =
blue <-> red with a neutral grey midpoint. One series -> one colour; emphasis = highlight + grey.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SURFACE = "#0b1220"
INK = "#f0efec"
INK2 = "#c3c2b7"
MUTED = "#898781"
GRID = "#1e2a3d"
AXIS = "#3a4558"
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]
NEUTRAL = "#5b6476"
SEQ = ["#0f1b2e", "#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"]
DIV = ["#e66767", "#a14848", "#383835", "#1c5cab", "#5598e7"]


def _setup():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.6, "grid.linestyle": "-", "axes.spines.top": False, "axes.spines.right": False,
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 9.5, "axes.titlesize": 11,
        "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
        "legend.labelcolor": INK2, "lines.linewidth": 2.0, "figure.dpi": 110, "savefig.dpi": 140,
        "axes.axisbelow": True,
    })
    return plt


def _save(fig, out: Path, name: str) -> str:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    fig.savefig(path, bbox_inches="tight", pad_inches=0.25)
    import matplotlib.pyplot as plt

    plt.close(fig)
    return path.name


def _seq_cmap():
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("wiot_seq", SEQ)


def _div_cmap():
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("wiot_div", DIV[::-1])


def _short(key: str) -> str:
    c, _, n = key.split("/")
    return f"{c.replace('Company_', 'C')}-N{n}"


def _dates(ts):
    return [datetime.fromtimestamp(int(t), tz=timezone.utc) for t in ts]


# ---------------------------------------------------------------------------
def fig_uplinks_daily(link: dict, out: Path) -> str:
    plt = _setup()
    import matplotlib.dates as mdates

    nodes = link["per_node"]
    all_days = sorted({d["day"] for n in nodes for d in n["daily"]})
    lo, hi = datetime.fromisoformat(all_days[0]), datetime.fromisoformat(all_days[-1])
    fig, axes = plt.subplots(len(nodes), 1, figsize=(9, 1.35 * len(nodes) + 0.6), sharex=True,
                             gridspec_kw={"hspace": 0.35})
    for ax, n in zip(np.atleast_1d(axes), nodes):
        days = [datetime.fromisoformat(d["day"]) for d in n["daily"]]
        ax.bar(days, [d["count"] for d in n["daily"]], width=0.8, color=SERIES[0], edgecolor=SURFACE, linewidth=1)
        ax.set_ylabel(_short(n["key"]), rotation=0, ha="right", va="center", color=INK2)
        ax.set_xlim(lo - (hi - lo) * 0.02, hi + (hi - lo) * 0.02)
        ax.grid(axis="x", visible=False)
    np.atleast_1d(axes)[0].set_title("Uplinks per day, by node (Africa/Cairo days)")
    np.atleast_1d(axes)[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    return _save(fig, out, "fig_uplinks_daily")


def fig_heatmap(link: dict, out: Path) -> str:
    plt = _setup()
    hm = link["heatmap"]
    mat = np.asarray(hm["counts"], dtype=float)
    fig, ax = plt.subplots(figsize=(9, max(3, 0.18 * len(hm["days"]) + 1)))
    im = ax.imshow(mat, aspect="auto", cmap=_seq_cmap(), interpolation="nearest")
    ax.set_yticks(range(len(hm["days"])))
    ax.set_yticklabels(hm["days"], fontsize=7)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Hour of day (Africa/Cairo)")
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("uplinks", color=INK2)
    cb.ax.tick_params(colors=MUTED)
    ax.set_title("Fleet uplinks by day x hour")
    return _save(fig, out, "fig_heatmap")


def fig_intervals(link: dict, summary_nodes: list[dict], out: Path) -> str:
    plt = _setup()
    nodes = link["per_node"]
    fig, axes = plt.subplots(1, len(nodes), figsize=(2.3 * len(nodes), 2.8), sharey=False)
    med = {n["key"] if "key" in n else f"{n['company']}/{n['region']}/{n['node_id']}": n["median_interval_s"]
           for n in summary_nodes}
    for ax, n in zip(np.atleast_1d(axes), nodes):
        e = np.asarray(n["interval_hist"]["edges"]); c = np.asarray(n["interval_hist"]["counts"])
        ax.bar(e[:-1], c, width=np.diff(e), align="edge", color=SERIES[0], edgecolor=SURFACE, linewidth=1)
        ax.set_xscale("log")
        m = med.get(n["key"])
        if m:
            ax.axvline(m, color=INK2, linewidth=1)
            ax.text(m * 1.2, ax.get_ylim()[1] * 0.92, f"median {m:.0f}s", color=INK2, fontsize=7.5)
        ax.set_title(_short(n["key"]), fontsize=9.5)
        ax.set_xlabel("seconds")
        ax.set_xlim(1, 1e6)
    fig.suptitle("Uplink inter-arrival time per node (log scale)", x=0.01, ha="left", fontweight="bold", color=INK)
    fig.tight_layout()
    return _save(fig, out, "fig_intervals")


def fig_store_forward(link: dict, out: Path) -> str:
    plt = _setup()
    rows = link["store_forward"]["by_mode"]
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(rows) + 1.4))
    for i, r in enumerate(rows):
        ax.plot([r["min"], r["max"]], [i, i], color=NEUTRAL, linewidth=1)
        ax.plot([r["p50"], r["p90"]], [i, i], color=SERIES[0], linewidth=5, solid_capstyle="butt")
        ax.scatter([r["p50"]], [i], s=60, color=INK, zorder=3, edgecolor=SURFACE, linewidth=2)
        ax.scatter([r["p99"]], [i], s=40, color=SERIES[1], zorder=3, marker="D", edgecolor=SURFACE, linewidth=1.5)
        ax.text(1.01, i, f"n={r['n']}", color=MUTED, fontsize=8, va="center", transform=ax.get_yaxis_transform())
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["mode"] for r in rows])
    ax.set_xscale("symlog", linthresh=10)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.set_xlabel("server receive time - node RTC measurement time (s, symlog)")
    ax.set_ylim(-0.6, len(rows) - 0.3)
    from matplotlib.lines import Line2D

    ax.legend(handles=[Line2D([], [], color=INK, marker="o", linestyle="", label="median"),
                       Line2D([], [], color=SERIES[0], linewidth=5, label="p50-p90"),
                       Line2D([], [], color=SERIES[1], marker="D", linestyle="", label="p99"),
                       Line2D([], [], color=NEUTRAL, linewidth=1, label="min-max")], loc="upper right", fontsize=8, ncol=2)
    ax.set_title("Store-and-forward delay of RTC-stamped samples by power mode")
    return _save(fig, out, "fig_store_forward")


def fig_battery(power: dict, out: Path) -> str:
    plt = _setup()
    import matplotlib.dates as mdates

    series = [b for b in power["battery"] if b["points"]]
    fig, axes = plt.subplots(len(series), 1, figsize=(9, 1.4 * len(series) + 0.6), sharex=True,
                             gridspec_kw={"hspace": 0.35})
    for ax, b in zip(np.atleast_1d(axes), series):
        pts = np.asarray(b["points"], dtype=float)
        # break the line across gaps > 3 h so separate test sessions are not joined
        brk = np.flatnonzero(np.diff(pts[:, 0]) > 3 * 3600) + 1
        for seg in np.split(pts, brk):
            ax.plot(_dates(seg[:, 0]), seg[:, 1], color=SERIES[0], linewidth=1.4, marker="o", markersize=2)
        ax.set_ylabel(_short(b["key"]), rotation=0, ha="right", va="center", color=INK2)
        ax.yaxis.set_major_locator(plt.MaxNLocator(3))
    np.atleast_1d(axes)[0].set_title("Battery / supply voltage (V) per node")
    np.atleast_1d(axes)[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    return _save(fig, out, "fig_battery")


def fig_energy(power: dict, out: Path, capacity: str = "5000") -> str:
    plt = _setup()
    em = power["energy_model"]
    keep = [c["name"] for c in em["configs"] if "gateway" not in c["name"] and "SIM node - connected" not in c["name"]]
    xs = em["intervals_s"]
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    for i, name in enumerate(keep[:5]):
        ys = [em["life_days"][name][str(x)][capacity] for x in xs]
        ax.plot(xs, ys, color=SERIES[i], marker="o", markersize=5, label=name, markeredgecolor=SURFACE)
        ax.text(xs[-1] * 1.15, ys[-1], name.split(" (")[0], color=INK2, fontsize=7.5, va="center")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xticks(xs); ax.set_xticklabels(["1 min", "5 min", "15 min", "1 h", "6 h"])
    ax.set_xlim(xs[0] * 0.8, xs[-1] * 6)
    ax.set_xlabel("reporting interval")
    ax.set_ylabel(f"estimated battery life (days, {capacity} mAh, 80% usable)")
    ax.legend(loc="upper left", fontsize=7.5)
    ax.set_title("Battery-life model from the power-down study (chip/module currents only)")
    return _save(fig, out, "fig_energy")


def _rate_dots(ax, labels, rates, lo, hi, ns, color=SERIES[0]):
    y = np.arange(len(labels))
    for i in range(len(labels)):
        if rates[i] is None:
            continue
        ax.plot([lo[i], hi[i]], [y[i], y[i]], color=NEUTRAL, linewidth=2, solid_capstyle="round")
        ax.scatter([rates[i]], [y[i]], s=55, color=color, zorder=3, edgecolor=SURFACE, linewidth=2)
        ax.text(1.02, y[i], f"n={ns[i]}", color=MUTED, fontsize=8, va="center", transform=ax.get_yaxis_transform())
    ax.set_yticks(y); ax.set_yticklabels(labels)
    ax.set_xlim(0, 1)
    ax.set_xlabel("ACK rate (Wilson 95% CI)")


def fig_cmd_by_type(commands: dict, out: Path) -> str:
    plt = _setup()
    rows = sorted([r for r in commands["by_type"] if r["ack_rate"] is not None], key=lambda r: r["ack_rate"])
    fig, ax = plt.subplots(figsize=(7.5, 0.33 * len(rows) + 1.3))
    _rate_dots(ax, [r["cmd_type"] for r in rows], [r["ack_rate"] for r in rows], [r["ci_low"] for r in rows],
               [r["ci_high"] for r in rows], [r["n"] - r["superseded"] for r in rows])
    ax.set_title("ACK rate by command type (non-superseded commands)")
    return _save(fig, out, "fig_cmd_by_type")


def fig_ack_recency(commands: dict, out: Path) -> str:
    plt = _setup()
    rows = commands["by_recency"]

    def lab(r):
        def f(s):
            return f"{s // 3600}h" if s >= 3600 else (f"{s // 60}m" if s >= 60 else f"{s}s")
        return f"{f(r['bin_low_s'])}-{f(r['bin_high_s'])}" if r["bin_high_s"] < 2_000_000 else f">= {f(r['bin_low_s'])}"

    fig, ax = plt.subplots(figsize=(7.5, 0.4 * len(rows) + 1.3))
    _rate_dots(ax, [lab(r) for r in rows], [r["ack_rate"] for r in rows], [r["ci_low"] for r in rows],
               [r["ci_high"] for r in rows], [r["n"] - r["superseded"] for r in rows])
    ax.set_ylabel("seconds since the node's last uplink")
    ax.invert_yaxis()
    ax.set_title("ACK rate vs. time since the node was last heard")
    return _save(fig, out, "fig_ack_recency")


def fig_ack_latency(commands: dict, out: Path) -> str:
    plt = _setup()
    h = commands["ack_latency"]["hist"]
    e, c = np.asarray(h["edges"]), np.asarray(h["counts"])
    fig, ax = plt.subplots(figsize=(8, 3.2))
    x = np.arange(len(c))
    ax.bar(x, c, width=0.85, color=SERIES[0], edgecolor=SURFACE, linewidth=1)
    ax.set_xticks(x); ax.set_xticklabels([f"{e[i]:g}-{e[i + 1]:g}" for i in range(len(c))], rotation=45, ha="right",
                                          fontsize=7.5)
    dl = int(np.searchsorted(e, 30))
    ax.axvline(dl - 0.5, color=SERIES[1], linewidth=1.5)
    ax.text(dl - 0.4, max(c) * 0.9, "30 s ACK deadline", color=INK2, fontsize=8)
    ax.set_xlabel("acknowledged_at - submitted_at (s)")
    ax.set_ylabel("commands")
    ax.grid(axis="x", visible=False)
    ax.set_title("Command ACK latency (acknowledged commands, incl. late)")
    return _save(fig, out, "fig_ack_latency")


def fig_model_cv(model: dict, out: Path) -> str:
    plt = _setup()
    rows = sorted(model["candidates"], key=lambda r: r["cv_pr_auc"])
    sel = model["selected"]["name"]
    fig, ax = plt.subplots(figsize=(7.5, 0.38 * len(rows) + 1.3))
    for i, r in enumerate(rows):
        col = SERIES[0] if r["name"] == sel else (SERIES[1] if r["kind"] == "baseline" else NEUTRAL)
        lo, hi = r["cv_pr_auc"] - r["cv_pr_auc_std"], r["cv_pr_auc"] + r["cv_pr_auc_std"]
        ax.plot([lo, hi], [i, i], color=col, linewidth=2, alpha=0.6, solid_capstyle="round")
        ax.scatter([r["cv_pr_auc"]], [i], s=60, color=col, zorder=3, edgecolor=SURFACE, linewidth=2)
        ax.text(1.01, i, f"{r['cv_pr_auc']:.3f}", color=INK2 if col != NEUTRAL else MUTED, fontsize=8, va="center",
                transform=ax.get_yaxis_transform())
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([r["name"] for r in rows])
    ax.set_xlim(0.3, 1.0)
    ax.set_xlabel("grouped-CV PR-AUC (mean +/- 1 SD over folds)")
    ax.set_title("Candidate models: selected (blue) vs. operator baseline (orange)")
    return _save(fig, out, "fig_model_cv")


def fig_holdout_curves(model: dict, out: Path) -> str:
    plt = _setup()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.5, 4))
    hm, hb = model["holdout"]["model"], model["holdout"]["baseline"]
    for key, col, name, ax in (("model", SERIES[0], "model", a1), ("baseline", SERIES[1], "baseline", a1)):
        pts = np.asarray(model["curves"]["pr"][key])
        auc = (hm if key == "model" else hb)["pr_auc"]["value"]
        ax.plot(pts[:, 0], pts[:, 1], color=col, label=f"{name} (AP {auc:.2f})", drawstyle="steps-post")
    a1.axhline(model["holdout"]["prevalence"], color=MUTED, linewidth=1)
    a1.text(0.02, model["holdout"]["prevalence"] + 0.02, "prevalence", color=MUTED, fontsize=8)
    a1.set_xlabel("recall"); a1.set_ylabel("precision"); a1.set_ylim(0, 1.02); a1.set_xlim(0, 1)
    a1.set_title("Hold-out precision-recall"); a1.legend(loc="lower left", fontsize=8)
    for key, col, name in (("model", SERIES[0], "model"), ("baseline", SERIES[1], "baseline")):
        pts = np.asarray(model["curves"]["roc"][key])
        auc = (hm if key == "model" else hb)["roc_auc"]["value"]
        a2.plot(pts[:, 0], pts[:, 1], color=col, label=f"{name} (AUC {auc:.2f})")
    a2.plot([0, 1], [0, 1], color=AXIS, linewidth=1)
    a2.set_xlabel("false-positive rate"); a2.set_ylabel("true-positive rate")
    a2.set_title("Hold-out ROC"); a2.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return _save(fig, out, "fig_holdout_curves")


def fig_calibration(model: dict, out: Path) -> str:
    plt = _setup()
    bins = model["calibration"]
    fig, ax = plt.subplots(figsize=(4.8, 4.4))
    ax.plot([0, 1], [0, 1], color=AXIS, linewidth=1)
    x = [b["mean_pred"] for b in bins]; y = [b["frac_pos"] for b in bins]
    ax.plot(x, y, color=SERIES[0], marker="o", markersize=7, markeredgecolor=SURFACE)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("mean predicted P(delivered)"); ax.set_ylabel("observed delivered share")
    ax.set_title("Calibration (train out-of-fold, decile bins)")
    return _save(fig, out, "fig_calibration")


def fig_shap(model: dict, out: Path) -> str:
    plt = _setup()
    rows = model["shap_global"][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 0.34 * len(rows) + 1.2))
    ax.barh(range(len(rows)), [r["mean_abs_shap"] for r in rows], color=SERIES[0], height=0.7,
            edgecolor=SURFACE, linewidth=1)
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([r["label"] for r in rows], fontsize=8.5)
    ax.set_xlabel("mean |SHAP| (calibrated log-odds of delivery)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Global feature importance (train set)")
    return _save(fig, out, "fig_shap")


def fig_tiers(model: dict, out: Path) -> str:
    plt = _setup()
    sel = model["selected"]
    tiers = ["LIKELY", "UNCERTAIN", "UNLIKELY"]
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    w = 0.38
    for j, (key, name, col) in enumerate((("tier_table_oof", "train OOF", SERIES[0]),
                                          ("tier_table_holdout", "hold-out", SERIES[2]))):
        tab = {r["tier"]: r for r in sel[key]}
        vals = [tab[t]["observed_ack_rate"] or 0 for t in tiers]
        xs = np.arange(3) + (j - 0.5) * w
        ax.bar(xs, vals, width=w - 0.04, color=col, label=name, edgecolor=SURFACE, linewidth=1)
        for x, t in zip(xs, tiers):
            ax.text(x, (tab[t]["observed_ack_rate"] or 0) + 0.02, f"n={tab[t]['n']}", ha="center", color=MUTED,
                    fontsize=7.5)
    ax.set_xticks(range(3)); ax.set_xticklabels(tiers)
    ax.set_ylim(0, 1.05); ax.set_ylabel("observed ACK rate")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="x", visible=False)
    ax.set_title("Delivery tiers: observed ACK rate per tier")
    return _save(fig, out, "fig_tiers")


def fig_firmware(firmware: dict, out: Path) -> str:
    plt = _setup()
    rows = sorted(firmware["profiles"], key=lambda r: r["flash_bytes"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 0.3 * len(rows) + 1.5), sharey=True)
    y = np.arange(len(rows))
    a1.barh(y, [r["flash_bytes"] / 1024 for r in rows], color=SERIES[0], height=0.7, edgecolor=SURFACE, linewidth=1)
    a1.axvline(128, color=SERIES[1], linewidth=1.2)
    a1.text(129, len(rows) - 1, "EEPROM sector\n(128 KiB)", color=INK2, fontsize=7.5, va="top")
    a1.set_xlabel("flash (KiB) of 256 KiB"); a1.set_title("Flash per build profile (latest build)")
    a2.barh(y, [r["ram_bytes"] / 1024 for r in rows], color=SERIES[2], height=0.7, edgecolor=SURFACE, linewidth=1)
    a2.set_xlim(0, 64); a2.set_xlabel("static RAM (KiB) of 64 KiB"); a2.set_title("Static RAM")
    a1.set_yticks(y); a1.set_yticklabels([r["name"] for r in rows], fontsize=8)
    for ax in (a1, a2):
        ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return _save(fig, out, "fig_firmware")


def fig_firmware_trend(firmware: dict, out: Path) -> str:
    plt = _setup()
    elf = [t for t in firmware["trend"] if t["source"] == "elf"]
    profiles = ["wor-lora", "rtc-lora", "gateway-wor", "normal-sim"]
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    for i, p in enumerate(profiles):
        pts = sorted((t["date"], t["flash_bytes"]) for t in elf if t["profile"] == p)
        if len(pts) < 2:
            continue
        xs = [datetime.strptime(d, "%Y%m%d") for d, _ in pts]
        ys = [b / 1024 for _, b in pts]
        ax.plot(xs, ys, color=SERIES[i], marker="o", markersize=5, markeredgecolor=SURFACE, label=p)
    import matplotlib.dates as mdates

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_ylabel("flash (KiB)")
    ax.legend(loc="center left", fontsize=8)
    ax.set_title("Flash footprint across build folders (Oct 4 -> Oct 30)")
    return _save(fig, out, "fig_firmware_trend")


def fig_sensor_corr(sensors: dict, out: Path) -> str:
    plt = _setup()
    ch = sensors["correlation"]["channels"]
    if not ch:
        return ""
    mat = np.asarray([[np.nan if v is None else v for v in row] for row in sensors["correlation"]["matrix"]])
    fig, ax = plt.subplots(figsize=(0.62 * len(ch) + 2.5, 0.55 * len(ch) + 1.8))
    im = ax.imshow(mat, cmap=_div_cmap(), vmin=-1, vmax=1)
    ax.set_xticks(range(len(ch))); ax.set_xticklabels(ch, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(ch))); ax.set_yticklabels(ch, fontsize=8)
    for i in range(len(ch)):
        for j in range(len(ch)):
            if np.isfinite(mat[i, j]) and i != j and abs(mat[i, j]) >= 0.5:
                ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=7, color=INK)
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.ax.tick_params(colors=MUTED)
    ax.set_title("Spearman correlation between sensor channels (blank: < 30 paired samples)")
    return _save(fig, out, "fig_sensor_corr")


def render_all(artifacts: dict[str, Any], out: Path) -> dict[str, str]:
    """Render every figure; returns {figure_id: filename}. Failures are reported, not fatal."""
    jobs = {
        "uplinks_daily": lambda: fig_uplinks_daily(artifacts["link"], out),
        "heatmap": lambda: fig_heatmap(artifacts["link"], out),
        "intervals": lambda: fig_intervals(artifacts["link"], artifacts["summary"]["nodes"], out),
        "store_forward": lambda: fig_store_forward(artifacts["link"], out),
        "battery": lambda: fig_battery(artifacts["power"], out),
        "energy": lambda: fig_energy(artifacts["power"], out),
        "cmd_by_type": lambda: fig_cmd_by_type(artifacts["commands"], out),
        "ack_recency": lambda: fig_ack_recency(artifacts["commands"], out),
        "ack_latency": lambda: fig_ack_latency(artifacts["commands"], out),
        "model_cv": lambda: fig_model_cv(artifacts["model"], out),
        "holdout_curves": lambda: fig_holdout_curves(artifacts["model"], out),
        "calibration": lambda: fig_calibration(artifacts["model"], out),
        "shap": lambda: fig_shap(artifacts["model"], out),
        "tiers": lambda: fig_tiers(artifacts["model"], out),
        "firmware": lambda: fig_firmware(artifacts["firmware"], out),
        "firmware_trend": lambda: fig_firmware_trend(artifacts["firmware"], out),
        "sensor_corr": lambda: fig_sensor_corr(artifacts["sensors"], out),
    }
    done: dict[str, str] = {}
    for name, job in jobs.items():
        try:
            fn = job()
            if fn:
                done[name] = fn
        except Exception as exc:  # pragma: no cover - a broken figure must not kill the pipeline
            print(f"  [figure {name}] failed: {exc!r}")
    return done
