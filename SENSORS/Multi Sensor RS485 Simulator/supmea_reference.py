"""Independent SUPMEA test oracle: integrate positive volumetric flow by calendar.

This module never imports a Modbus encoder or the node accumulator. Its totals
are session measurements, not full historical calendar consumption. No D/M/Y
registers are created. UTC time is advanced from monotonic elapsed simulation time.
"""
from datetime import datetime, time as day_time, timedelta, timezone
import math
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def calendar_zone(name):
    if name == "UTC":
        return timezone.utc
    if name.startswith(("+", "-")):
        try:
            hours, minutes = map(int, name[1:].split(":"))
            if not (0 <= hours <= 23 and 0 <= minutes <= 59):
                raise ValueError()
            return timezone(timedelta(minutes=(1 if name[0] == "+" else -1) * (hours * 60 + minutes)))
        except (ValueError, TypeError):
            raise ValueError("Fixed timezone must be +HH:MM or -HH:MM") from None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise ValueError("Timezone unavailable. Install tzdata or select UTC / +HH:MM.") from None


def parse_utc_start(text):
    """Accept explicit ISO UTC/offset time, never an ambiguous naive local time."""
    if not text.strip():
        return time.time()
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Include Z or an explicit UTC offset in the start time")
    return value.timestamp()


class SupmeaReference:
    """Double-precision flow integral split at actual local day boundaries."""
    def __init__(self, zone="Africa/Cairo", epoch=None):
        self.zone_name = zone
        self.zone = calendar_zone(zone)
        self.epoch = time.time() if epoch is None else float(epoch)
        if not math.isfinite(self.epoch):
            raise ValueError("Reference epoch must be finite")
        self.started_epoch = self.epoch
        self.day_m3 = self.month_m3 = self.year_m3 = 0.0
        self.session_m3 = 0.0
        self.keys = self._keys(self.epoch)
        self.status = "Ready; session totals start at zero"

    def _keys(self, epoch):
        local = datetime.fromtimestamp(epoch, self.zone)
        return local.date().isoformat(), local.strftime("%Y-%m"), str(local.year)

    def _roll(self, epoch):
        keys = self._keys(epoch)
        for index, attribute in enumerate(("day_m3", "month_m3", "year_m3")):
            if keys[index] != self.keys[index]:
                setattr(self, attribute, 0.0)
        self.keys = keys

    def advance(self, seconds, flow_m3h):
        """Integrate positive flow; None advances clock without assuming volume."""
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed seconds must be finite and nonnegative")
        if flow_m3h is not None and not math.isfinite(float(flow_m3h)):
            raise ValueError("Flow must be finite")
        rate = max(0.0, float(flow_m3h)) if flow_m3h is not None else 0.0
        end = self.epoch + seconds
        # Reject unreasonable test jumps before mutating state; real-time use is x1.
        if seconds > 366 * 86400:
            raise ValueError("One reference update cannot exceed 366 days")
        cursor = self.epoch
        while cursor < end:
            self._roll(cursor)
            local = datetime.fromtimestamp(cursor, self.zone)
            midnight = datetime.combine(local.date() + timedelta(days=1), day_time(), self.zone).timestamp()
            boundary = min(end, midnight)
            if boundary <= cursor:
                raise ValueError("Timezone failed to produce a future day boundary")
            volume = rate * (boundary - cursor) / 3600.0
            self.day_m3 += volume
            self.month_m3 += volume
            self.year_m3 += volume
            self.session_m3 += volume
            cursor = boundary
        self.epoch = end
        self._roll(end)
        self.status = ("Integrating forward flow" if flow_m3h is not None
                       else "Paused: auto totalizers off / unsupported mass-flow unit")

    def snapshot(self):
        return {
            "timezone": self.zone_name,
            "started_utc": datetime.fromtimestamp(self.started_epoch, timezone.utc).isoformat(),
            "clock_utc": datetime.fromtimestamp(self.epoch, timezone.utc).isoformat(),
            "clock_local": datetime.fromtimestamp(self.epoch, self.zone).isoformat(),
            "day_key": self.keys[0], "month_key": self.keys[1], "year_key": self.keys[2],
            "today_m3": self.day_m3, "month_m3": self.month_m3,
            "year_m3": self.year_m3, "session_m3": self.session_m3,
            "status": self.status, "scope": "Since reference session start; not full prior history",
            "wire": "Display/export only; never transmitted on RS485",
        }
