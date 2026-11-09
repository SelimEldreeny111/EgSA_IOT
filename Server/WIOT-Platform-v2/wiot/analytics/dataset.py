"""Read-only loaders for the WIOT databases and the shared command feature builder.

All SQLite databases are opened with ``mode=ro`` URIs; nothing in this module writes to them.

The single feature builder :func:`command_features` is used both to build the training
set and, through :func:`build_live_features`, to score a hypothetical command against the
live databases, so there is no train/serve skew. Every feature is computed *as of* the
command's ``submitted_at``: only uplinks with ``timestamp < submitted_at`` and only
previous-command outcomes that were already observable before ``submitted_at`` are used.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .common import local_hour

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
POWER_MODE_NAMES: dict[int, str] = {0: "UNKNOWN", 1: "NORMAL", 2: "RTC_PERIODIC", 3: "REMOTE_WAKE",
                                    4: "RTC_QUEUED", 5: "LORA_WOR_STOP"}
POWER_STATE_NAMES: dict[int, str] = {0: "UNKNOWN", 1: "ACTIVE", 2: "REACHABLE_IDLE"}
FLOW_METER_NAMES: dict[int, str] = {0: "none", 1: "TUF", 2: "Supmea"}

#: Command type -> family. GOSTM asks the node to send telemetry now (a query; it always replies).
CMD_FAMILY: dict[str, str] = {
    "SRATE": "config", "STRAN": "config", "STIME": "time", "GOSTM": "query", "VALVE": "valve",
    "WAKE": "power", "CLEAR_POWER_RESETS": "maintenance", "CLEAR_WDT_RESETS": "maintenance",
    "CLEAR_FLASH": "flash", "FLASH_STATUS": "flash", "FLASH_LAST": "flash", "FLASH_TODAY": "flash",
    "FLASH_CANCEL": "flash",
}
UPLINK_TYPES = ("Status", "Telemetry")
SECONDS_CAP = 30 * 86400          # "never seen" / very old is capped at 30 days
BURST_WINDOW_S = 300              # commands to the same node in the previous 5 minutes
ACK_HISTORY_LEN = 10              # last N resolved commands for the smoothed ack rate

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    kind: str            # "number" | "category"
    group: str           # command | identity | link | power | history | time
    log: bool = False    # log1p-transform before scaling (models only; the dict keeps raw values)


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec("cmd_type", "Command type", "category", "command"),
    FeatureSpec("cmd_family", "Command family", "category", "command"),
    FeatureSpec("node_key", "Node (company/region/node)", "category", "identity"),
    FeatureSpec("company", "Company", "category", "identity"),
    FeatureSpec("s_since_uplink", "Seconds since last uplink", "number", "link", log=True),
    FeatureSpec("s_since_status", "Seconds since last Status", "number", "link", log=True),
    FeatureSpec("uplinks_10m", "Uplinks in previous 10 min", "number", "link"),
    FeatureSpec("uplinks_60m", "Uplinks in previous 60 min", "number", "link"),
    FeatureSpec("recent_median_interval_s", "Median uplink interval, last 20 (s)", "number", "link", log=True),
    FeatureSpec("last_uplink_was_ack", "Last uplink was a command ACK", "number", "link"),
    FeatureSpec("last_power_mode", "Last reported power mode", "category", "power"),
    FeatureSpec("last_power_state", "Last reported power state", "category", "power"),
    FeatureSpec("battery_v", "Last battery voltage (V)", "number", "power"),
    FeatureSpec("wake_remaining_s", "Wake seconds remaining at last uplink", "number", "power"),
    FeatureSpec("wdt_resets", "Watchdog reset counter (last)", "number", "power"),
    FeatureSpec("power_resets", "Power reset counter (last)", "number", "power"),
    FeatureSpec("node_ack_rate", "Node ACK rate, last 10 resolved (smoothed)", "number", "history"),
    FeatureSpec("prev_cmd_acked", "Previous resolved command ACKed", "category", "history"),
    FeatureSpec("s_since_last_ack", "Seconds since node last ACKed", "number", "history", log=True),
    FeatureSpec("cmds_prev_5m", "Commands to node in previous 5 min", "number", "history"),
    FeatureSpec("hour_local", "Hour of day (Africa/Cairo)", "number", "time"),
)
FEATURES: list[str] = [f.name for f in FEATURE_SPECS]
FEATURE_LABELS: dict[str, str] = {f.name: f.label for f in FEATURE_SPECS}
CATEGORICAL: list[str] = [f.name for f in FEATURE_SPECS if f.kind == "category"]
NUMERIC: list[str] = [f.name for f in FEATURE_SPECS if f.kind == "number"]
LOG_FEATURES: list[str] = [f.name for f in FEATURE_SPECS if f.log]
IDENTITY_FEATURES: list[str] = [f.name for f in FEATURE_SPECS if f.group == "identity"]
HISTORY_FEATURES: list[str] = [f.name for f in FEATURE_SPECS if f.group == "history"]


# ---------------------------------------------------------------------------
# Connections and paths
# ---------------------------------------------------------------------------
def connect_ro(path: Path | str) -> sqlite3.Connection:
    """Open an SQLite database strictly read-only (URI ``mode=ro``)."""
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(p)
    return sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)


def message_db_paths(data_dir: Path | str) -> list[Path]:
    return sorted((Path(data_dir) / "messages_dbs").glob("*.db"))


def command_db_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "command_lifecycle.db"


def node_key(company: str, region: str, node_id: int) -> str:
    return f"{company}/{region}/{int(node_id)}"


def _read_sql(path: Path, sql: str, params: Iterable = ()) -> pd.DataFrame:
    con = connect_ro(path)
    try:
        return pd.read_sql_query(sql, con, params=list(params))
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def _where(filters: dict[str, object], time_col: str, before: int | None) -> tuple[str, list]:
    clauses, params = [], []
    for col, val in filters.items():
        if val is not None:
            clauses.append(f"{col} = ?")
            params.append(val)
    if before is not None:
        clauses.append(f"{time_col} < ?")
        params.append(int(before))
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _message_paths_for(data_dir: Path | str, company: str | None) -> list[Path]:
    paths = message_db_paths(data_dir)
    if company is None:
        return paths
    if not _SAFE_NAME.match(company):
        raise ValueError(f"invalid company name: {company!r}")
    exact = [p for p in paths if p.stem == company]
    return exact or paths  # fall back to scanning every DB (the WHERE clause still filters)


def load_messages(data_dir: Path | str, company: str | None = None, region: str | None = None,
                  node_id: int | None = None, before: int | None = None) -> pd.DataFrame:
    """All decoded MQTT messages (every company DB), sorted by server-received time.

    Adds ``node_key``, ``is_uplink`` (Status/Telemetry) and ``is_ack`` (uplink that is a
    command ACK: ``time_source == 'command_ack_cached'`` or ``CMD_ACK`` in details).
    """
    frames = []
    for path in _message_paths_for(data_dir, company):
        where, params = _where({"company": company, "region": region, "node_id": node_id}, "timestamp", before)
        df = _read_sql(path, f"SELECT * FROM messages{where}", params)
        df["source_db"] = path.stem
        frames.append(df)
    msgs = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if msgs.empty:
        return _empty_messages()
    msgs["region"] = msgs["region"].fillna("Region_1").astype(str)
    msgs["company"] = msgs["company"].fillna(msgs["source_db"]).astype(str)
    msgs["type"] = msgs["type"].astype(str)
    msgs["details"] = msgs["details"].fillna("").astype(str)
    msgs["time_source"] = msgs["time_source"].fillna("").astype(str)
    msgs["timestamp"] = msgs["timestamp"].astype("int64")
    msgs["measured_at"] = msgs["measured_at"].fillna(msgs["timestamp"]).astype("int64")
    msgs["node_id"] = msgs["node_id"].astype("int64")
    msgs["node_key"] = [node_key(c, r, n) for c, r, n in zip(msgs["company"], msgs["region"], msgs["node_id"])]
    msgs["is_uplink"] = msgs["type"].isin(UPLINK_TYPES)
    msgs["is_ack"] = msgs["is_uplink"] & ((msgs["time_source"] == "command_ack_cached")
                                         | msgs["details"].str.contains("CMD_ACK", regex=False))
    return msgs.sort_values(["timestamp", "id"], kind="stable").reset_index(drop=True)


def _empty_messages() -> pd.DataFrame:
    cols = ["id", "timestamp", "type", "node_id", "company", "region", "details", "time_source",
            "power_mode", "power_state", "battery_voltage", "wake_remaining_seconds", "wdt_reset_count",
            "power_reset_count", "measured_at", "node_key", "is_uplink", "is_ack"]
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})


def load_meter_samples(data_dir: Path | str) -> pd.DataFrame:
    frames = []
    for path in message_db_paths(data_dir):
        df = _read_sql(path, "SELECT * FROM meter_samples")
        df["company"] = path.stem
        frames.append(df)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out["node_key"] = [node_key(c, r, n) for c, r, n in zip(out["company"], out["region"], out["node_id"])]
    return out


def load_consumption_periods(data_dir: Path | str) -> pd.DataFrame:
    frames = []
    for path in message_db_paths(data_dir):
        df = _read_sql(path, "SELECT * FROM consumption_periods")
        df["company"] = path.stem
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_command_events(data_dir: Path | str) -> pd.DataFrame:
    return _read_sql(command_db_path(data_dir), "SELECT * FROM command_events ORDER BY timestamp, id")


def load_command_receipts(data_dir: Path | str) -> pd.DataFrame:
    return _read_sql(command_db_path(data_dir), "SELECT * FROM command_receipts")


def load_commands(data_dir: Path | str, company: str | None = None, region: str | None = None,
                  node_id: int | None = None, before: int | None = None) -> pd.DataFrame:
    """Command journal (``pending_commands``) joined with node receipts and labels.

    Added columns: ``reply_at`` / ``reply_success`` / ``reply_late`` (from ``command_receipts``),
    ``node_key``, ``cmd_family``, and the targets ``labelled`` (non-superseded), ``y_ack``
    (acknowledged, late or not), ``y_ontime`` (acknowledged and not late) and ``y_reply``
    (any node reply, i.e. acknowledged or rejected).
    """
    path = command_db_path(data_dir)
    where, params = _where({"company": company, "region": region, "node_id": node_id}, "submitted_at", before)
    cmds = _read_sql(path, f"SELECT * FROM pending_commands{where}", params)
    rec = _read_sql(path, "SELECT request_id, success AS reply_success, received_at AS reply_at, "
                          "late AS reply_late FROM command_receipts")
    cmds = cmds.merge(rec, on="request_id", how="left")
    cmds = cmds[cmds["submitted_at"].notna()].copy()
    cmds["submitted_at"] = cmds["submitted_at"].astype("int64")
    cmds["region"] = cmds["region"].fillna("Region_1").astype(str)
    cmds["company"] = cmds["company"].astype(str)
    cmds["cmd_type"] = cmds["cmd_type"].astype(str)
    cmds["state"] = cmds["state"].astype(str)
    cmds["node_key"] = [node_key(c, r, n) for c, r, n in zip(cmds["company"], cmds["region"], cmds["node_id"])]
    cmds["cmd_family"] = cmds["cmd_type"].map(CMD_FAMILY).fillna("other")
    cmds["labelled"] = cmds["state"] != "superseded"
    cmds["y_ack"] = (cmds["state"] == "acknowledged").astype(int)
    cmds["y_ontime"] = ((cmds["state"] == "acknowledged") & (cmds["reply_late"].fillna(0) == 0)).astype(int)
    cmds["y_reply"] = cmds["state"].isin(["acknowledged", "rejected"]).astype(int)
    return cmds.sort_values(["submitted_at", "id"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Feature builder (shared by training and live scoring)
# ---------------------------------------------------------------------------
@dataclass
class _UplinkIndex:
    ts: np.ndarray
    status_ts: np.ndarray
    is_ack: np.ndarray
    power_mode: np.ndarray
    power_state: np.ndarray
    battery: np.ndarray
    wake_remaining: np.ndarray
    wdt: np.ndarray
    pwr: np.ndarray


@dataclass
class _HistoryIndex:
    submitted: np.ndarray
    reply_at: np.ndarray
    reply_success: np.ndarray
    deadline: np.ndarray


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> np.ndarray:
    if col not in df:
        return np.full(len(df), default, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(default).to_numpy(dtype=float)


def _ensure_keys(df: pd.DataFrame) -> pd.Series:
    if "node_key" in df:
        return df["node_key"].astype(str)
    region = df["region"] if "region" in df else pd.Series("Region_1", index=df.index)
    return pd.Series([node_key(c, r, n) for c, r, n in zip(df["company"], region, df["node_id"])], index=df.index)


def _uplink_indices(messages: pd.DataFrame) -> dict[str, _UplinkIndex]:
    if messages is None or len(messages) == 0:
        return {}
    m = messages[messages["type"].astype(str).isin(UPLINK_TYPES)].copy()
    if m.empty:
        return {}
    m["node_key"] = _ensure_keys(m)
    if "is_ack" not in m:
        ts_src = m.get("time_source", pd.Series("", index=m.index)).fillna("").astype(str)
        det = m.get("details", pd.Series("", index=m.index)).fillna("").astype(str)
        m["is_ack"] = (ts_src == "command_ack_cached") | det.str.contains("CMD_ACK", regex=False)
    sort_cols = ["timestamp", "id"] if "id" in m else ["timestamp"]
    m = m.sort_values(sort_cols, kind="stable")
    out: dict[str, _UplinkIndex] = {}
    for key, g in m.groupby("node_key", sort=False):
        ts = g["timestamp"].to_numpy(dtype="int64")
        out[key] = _UplinkIndex(
            ts=ts,
            status_ts=ts[(g["type"].astype(str) == "Status").to_numpy()],
            is_ack=g["is_ack"].to_numpy(dtype=bool),
            power_mode=_num(g, "power_mode").astype(int),
            power_state=_num(g, "power_state").astype(int),
            battery=_num(g, "battery_voltage", np.nan),
            wake_remaining=_num(g, "wake_remaining_seconds"),
            wdt=_num(g, "wdt_reset_count"),
            pwr=_num(g, "power_reset_count"),
        )
    return out


def _history_indices(history: pd.DataFrame) -> dict[str, _HistoryIndex]:
    if history is None or len(history) == 0:
        return {}
    h = history.copy()
    h["node_key"] = _ensure_keys(h)
    h = h[h["submitted_at"].notna()].sort_values("submitted_at", kind="stable")
    out: dict[str, _HistoryIndex] = {}
    for key, g in h.groupby("node_key", sort=False):
        sub = g["submitted_at"].to_numpy(dtype=float)
        deadline = _num(g, "ack_deadline", np.nan)
        deadline = np.where(np.isnan(deadline), sub + 30, deadline)
        out[key] = _HistoryIndex(submitted=sub, reply_at=_num(g, "reply_at", np.nan),
                                 reply_success=_num(g, "reply_success", 0.0), deadline=deadline)
    return out


def _cap(seconds: float) -> float:
    return float(min(max(seconds, 0.0), SECONDS_CAP))


def link_features(u: _UplinkIndex | None, t: int) -> dict[str, object]:
    """Uplink-derived features using only uplinks with ``timestamp < t``."""
    k = 0 if u is None else int(np.searchsorted(u.ts, t, side="left"))
    if u is None or k == 0:
        return {"s_since_uplink": float(SECONDS_CAP), "s_since_status": float(SECONDS_CAP), "uplinks_10m": 0,
                "uplinks_60m": 0, "recent_median_interval_s": float(SECONDS_CAP), "last_uplink_was_ack": 0,
                "last_power_mode": POWER_MODE_NAMES[0], "last_power_state": POWER_STATE_NAMES[0],
                "battery_v": np.nan, "wake_remaining_s": 0.0, "wdt_resets": 0.0, "power_resets": 0.0}
    last = k - 1
    ks = int(np.searchsorted(u.status_ts, t, side="left"))
    recent = u.ts[max(0, k - 21):k]
    return {
        "s_since_uplink": _cap(t - u.ts[last]),
        "s_since_status": _cap(t - u.status_ts[ks - 1]) if ks else float(SECONDS_CAP),
        "uplinks_10m": int(k - np.searchsorted(u.ts, t - 600, side="left")),
        "uplinks_60m": int(k - np.searchsorted(u.ts, t - 3600, side="left")),
        "recent_median_interval_s": _cap(float(np.median(np.diff(recent)))) if recent.size >= 2 else float(SECONDS_CAP),
        "last_uplink_was_ack": int(bool(u.is_ack[last])),
        "last_power_mode": POWER_MODE_NAMES.get(int(u.power_mode[last]), POWER_MODE_NAMES[0]),
        "last_power_state": POWER_STATE_NAMES.get(int(u.power_state[last]), POWER_STATE_NAMES[0]),
        "battery_v": float(u.battery[last]) if u.battery[last] > 0 else np.nan,
        "wake_remaining_s": float(u.wake_remaining[last]),
        "wdt_resets": float(u.wdt[last]),
        "power_resets": float(u.pwr[last]),
    }


def history_features(h: _HistoryIndex | None, t: int) -> dict[str, object]:
    """Previous-command features, using only outcomes observable before ``t``.

    A previous command counts as ACKed if its node reply arrived before ``t`` with success,
    as not-ACKed if a reply arrived with failure or its ACK deadline passed before ``t``
    without a reply, and is ignored while still unresolved at ``t``.
    """
    if h is None:
        return {"node_ack_rate": 0.5, "prev_cmd_acked": "none",
                "s_since_last_ack": float(SECONDS_CAP), "cmds_prev_5m": 0}
    j = int(np.searchsorted(h.submitted, t, side="left"))
    rep, succ, dl = h.reply_at[:j], h.reply_success[:j], h.deadline[:j]
    replied = np.nan_to_num(rep, nan=np.inf) < t
    outcome = np.where(replied, (succ == 1).astype(float), np.where(dl < t, 0.0, np.nan))
    resolved = outcome[~np.isnan(outcome)]
    last = resolved[-ACK_HISTORY_LEN:]
    acked_times = rep[replied & (succ == 1)]
    return {
        "node_ack_rate": float((last.sum() + 1.0) / (last.size + 2.0)),
        "prev_cmd_acked": "none" if resolved.size == 0 else ("yes" if resolved[-1] == 1 else "no"),
        "s_since_last_ack": _cap(t - float(acked_times.max())) if acked_times.size else float(SECONDS_CAP),
        "cmds_prev_5m": int(j - np.searchsorted(h.submitted, t - BURST_WINDOW_S, side="left")),
    }


def command_features(cmd_rows: pd.DataFrame, messages: pd.DataFrame,
                     history: pd.DataFrame | None = None) -> pd.DataFrame:
    """Features known at submission time for each command row.

    Parameters
    ----------
    cmd_rows:
        Commands to featurise; needs ``company``, ``node_id``, ``cmd_type``, ``submitted_at``
        (``region`` defaults to ``Region_1``).
    messages:
        Decoded messages (as from :func:`load_messages`). Only uplinks strictly before each
        command's ``submitted_at`` are used.
    history:
        Command journal used for the per-node ACK-history features (as from
        :func:`load_commands`). Defaults to ``cmd_rows`` itself. Only outcomes observable
        strictly before ``submitted_at`` are used.

    Returns
    -------
    DataFrame indexed like ``cmd_rows`` with columns :data:`FEATURES`.
    """
    rows = cmd_rows.copy()
    if "region" not in rows:
        rows["region"] = "Region_1"
    keys = _ensure_keys(rows)
    uplinks = _uplink_indices(messages)
    hist = _history_indices(rows if history is None else history)
    t_all = rows["submitted_at"].astype("int64").to_numpy()
    records = []
    for key, t, cmd_type, company in zip(keys, t_all, rows["cmd_type"].astype(str), rows["company"].astype(str)):
        rec: dict[str, object] = {"cmd_type": cmd_type, "cmd_family": CMD_FAMILY.get(cmd_type, "other"),
                                  "node_key": key, "company": company}
        rec.update(link_features(uplinks.get(key), int(t)))
        rec.update(history_features(hist.get(key), int(t)))
        records.append(rec)
    out = pd.DataFrame.from_records(records, index=rows.index)
    out["hour_local"] = local_hour(t_all) if len(t_all) else []
    for col in CATEGORICAL:
        out[col] = out[col].astype(str)
    for col in NUMERIC:
        out[col] = out[col].astype(float)
    return out[FEATURES]


def build_live_features(company: str, region: str, node_id: int, cmd_type: str, now: int | float,
                        data_dir: Path | str) -> dict[str, object]:
    """Features for one hypothetical command submitted at ``now``, from the live databases."""
    now_i = int(now)
    msgs = load_messages(data_dir, company=company, region=region, node_id=int(node_id), before=now_i)
    hist = load_commands(data_dir, company=company, region=region, node_id=int(node_id), before=now_i)
    row = pd.DataFrame([{"company": company, "region": region, "node_id": int(node_id),
                         "cmd_type": str(cmd_type), "submitted_at": now_i}])
    feats = command_features(row, msgs, history=hist).iloc[0].to_dict()
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in feats.items()}


def training_frame(data_dir: Path | str, messages: pd.DataFrame | None = None,
                   commands: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(features, commands) for every submitted command; filter on ``commands.labelled`` to train."""
    msgs = load_messages(data_dir) if messages is None else messages
    cmds = load_commands(data_dir) if commands is None else commands
    return command_features(cmds, msgs, history=cmds), cmds
