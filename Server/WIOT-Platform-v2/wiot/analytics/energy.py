"""Battery-life model from the project's power-down study.

Currents are hard-coded from ``POWER_DOWN_MODE_STUDY.md`` section 4, "Theoretical whole-system
idle budgets" (table at lines 160-169 of the study): the "Active/listening reference" column is
used as the active current and "Estimated resting current" as the sleep current. Where the study
gives a range (e.g. "6.1-17.1 mA") the midpoint is used and the range is kept for reference.
The study's own caveat applies: these are chip/module values (STM32 + radio only) that exclude
sensors, regulators, LEDs and PCB leakage (section 2), and exclude transmit bursts (line 171), so
a transmit term and an optional battery-divider overhead (section 5.1, 0.236 mA at 7.4 V) are
added explicitly below.

    I_avg = (I_active * (t_active - t_tx) + I_tx * t_tx + I_sleep * (T - t_active)) / T
    life_days = usable_capacity_mAh / I_avg / 24
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

USABLE_FRACTION = 0.80                  # usable share of nominal capacity (derating assumption)
BATTERY_DIVIDER_MA = 0.236              # POWER_DOWN_MODE_STUDY.md section 5.1 (7.4 V row)
INTERVALS_S = [60, 300, 900, 3600, 21600]
CAPACITIES_MAH = [2000, 5000, 10000]


@dataclass(frozen=True)
class PowerConfig:
    name: str
    transport: str
    active_ma: float
    sleep_ma: float
    active_s_per_report: float
    tx_ma: float
    tx_s_per_report: float
    remote_downlink: str
    study_active: str
    study_sleep: str
    study_line: int


# Study lines 162-169. Active window assumptions: LoRa 8 s (wake, sample, send, short command
# window), Wi-Fi 20 s (ESP8266 reconnect + MQTT publish), SIM 30 s (registration + GPRS + MQTT).
# TX assumptions: E32 110 mA at 20 dBm (study 3.2) for 0.5 s per report; SIM800L GPRS ~340 mA
# (midpoint of 150-530 mA, study 3.4) for 5 s per report; ESP8266 TX is inside its 80 mA average.
CONFIGS: list[PowerConfig] = [
    PowerConfig("LoRa node - remote wake (Stop + E32 WOR)", "LoRa", 37.5, 0.042, 8, 110, 0.5,
                "yes (WOR preamble + AUX wake)", "37.5 mA", "0.042 mA", 162),
    PowerConfig("LoRa node - scheduled only (Standby + E32 sleep)", "LoRa", 37.5, 0.006, 8, 110, 0.5,
                "no (queued to next wake)", "37.5 mA", "0.006 mA", 163),
    PowerConfig("Wi-Fi node - connected (Sleep + ESP light-sleep)", "Wi-Fi", 102.5, 11.6, 20, 102.5, 0,
                "yes (MQTT keep-alive)", "102.5 mA", "6.1-17.1 mA", 164),
    PowerConfig("Wi-Fi node - scheduled only (Standby + ESP deep-sleep)", "Wi-Fi", 102.5, 0.023, 20, 102.5, 0,
                "no (reconnect and poll)", "102.5 mA", "0.023 mA", 165),
    PowerConfig("SIM node - connected (Sleep + SIM network sleep)", "SIM", 38.55, 12.15, 30, 340, 5,
                "conditional", "35.9-41.2 mA", "6.2-18.1 mA", 166),
    PowerConfig("SIM node - scheduled only (Standby + SIM power-down)", "SIM", 38.55, 0.128, 30, 340, 5,
                "no (re-registration)", "35.9-41.2 mA", "0.053-0.203 mA", 167),
    PowerConfig("LoRa + Wi-Fi gateway (Sleep + E32 WOR + ESP light-sleep)", "LoRa+Wi-Fi", 117.5, 11.6, 20, 117.5, 0,
                "yes", "117.5 mA", "6.1-17.1 mA", 168),
    PowerConfig("LoRa + SIM gateway (Sleep + E32 WOR + SIM network sleep)", "LoRa+SIM", 53.55, 12.2, 30, 340, 5,
                "conditional", "50.9-56.2 mA", "6.2-18.2 mA", 169),
]


def average_current_ma(cfg: PowerConfig, interval_s: float, overhead_ma: float = 0.0) -> float:
    t_a = min(cfg.active_s_per_report, interval_s)
    t_tx = min(cfg.tx_s_per_report, t_a)
    charge = cfg.active_ma * (t_a - t_tx) + cfg.tx_ma * t_tx + cfg.sleep_ma * (interval_s - t_a)
    return charge / interval_s + overhead_ma


def life_days(cfg: PowerConfig, interval_s: float, capacity_mah: float, overhead_ma: float = 0.0) -> float:
    return capacity_mah * USABLE_FRACTION / average_current_ma(cfg, interval_s, overhead_ma) / 24.0


def energy_model() -> dict:
    def table(overhead: float) -> dict:
        return {c.name: {str(t): {str(cap): life_days(c, t, cap, overhead) for cap in CAPACITIES_MAH}
                         for t in INTERVALS_S} for c in CONFIGS}

    return {
        "source": "POWER_DOWN_MODE_STUDY.md section 4, table lines 160-169 (+ sections 3.2, 3.4, 5.1)",
        "assumptions": [
            "Active current = study 'Active/listening reference'; sleep current = 'Estimated resting current'; "
            "ranges replaced by their midpoint.",
            "Active window per report: LoRa 8 s, Wi-Fi 20 s, SIM 30 s (wake, sample, connect, publish, command window).",
            "Transmit burst per report: LoRa E32 110 mA for 0.5 s; SIM800L GPRS 340 mA for 5 s; ESP8266 TX is inside "
            "its 80 mA active average.",
            f"Usable capacity = {USABLE_FRACTION:.0%} of nominal; no temperature or self-discharge derating.",
            "Chip/module currents only (STM32 + radio): sensors, RS485, regulators, LEDs and leakage are excluded, "
            "as stated in the study (section 2). 'life_days_with_divider' adds the existing battery divider drain "
            f"({BATTERY_DIVIDER_MA} mA at 7.4 V, study section 5.1).",
            "Gateways are normally mains/solar powered; they are included for comparison only.",
        ],
        "configs": [{**{k: v for k, v in asdict(c).items()},
                     "avg_ma": {str(t): average_current_ma(c, t) for t in INTERVALS_S}} for c in CONFIGS],
        "intervals_s": INTERVALS_S, "capacities_mah": CAPACITIES_MAH,
        "usable_fraction": USABLE_FRACTION, "battery_divider_ma": BATTERY_DIVIDER_MA,
        "life_days": table(0.0), "life_days_with_divider": table(BATTERY_DIVIDER_MA),
    }
