"""Regional dashboards for ministries and water authorities (R2.5, point 62).

Aggregates every company that has a farm layout by its *area* (the company's country and the farm's location
text, e.g. "EG · East Owainat"): number of farms and fields, irrigated area, water applied this month and its depth,
mean soil moisture, share of fields under / over-irrigated (7-day index), open alerts and mean NDVI.

No farm-level data is exposed: an area with fewer farms than ``WIOT_REGIONAL_MIN_FARMS`` (default 3) is reported
only as "suppressed" with its farm count, so a single farm cannot be identified.
"""
from __future__ import annotations

from datetime import date, timedelta


class RegionalService:
    def __init__(self, settings, main, org, farm, water, telemetry, alert_store, satellite=None):
        self.settings = settings
        self.main = main
        self.org = org
        self.farm = farm
        self.water = water
        self.telemetry = telemetry
        self.alert_store = alert_store
        self.satellite = satellite

    def _farm(self, company: str) -> dict | None:
        layout = self.farm.store.get(company)
        if layout is None or not layout.zones:
            return None
        profile = self.org.get_company(company) or {}
        today = self.water._today(company)
        start = today.replace(day=1)
        area = sum(z.area_ha() for z in layout.zones)
        water = sum(self.water._zone_volume(company, z, start, today + timedelta(days=1)) for z in layout.zones)
        region = layout.zones[0].region
        fleet = {n["node_id"]: n for n in self.telemetry.fleet(company, region)}
        wx = self.farm.weather.get(*layout.site.center)
        moist, index = [], []
        for z in layout.zones:
            st = self.farm.zone_state(z, fleet.get(z.node_id) if z.node_id else None, layout, wx, company)
            if st.get("moisture") is not None and st.get("status") not in ("offline", "no_data"):
                moist.append(st["moisture"])
            if (st.get("irrigation_index") or {}).get("status") in ("under", "over", "on_target"):
                index.append(st["irrigation_index"]["status"])
        ndvi = [v["mean"] for v in (self.satellite.latest_ndvi(company) if self.satellite else {}).values()]
        alerts = self.alert_store.summary(company)
        key = f"{profile.get('country') or '--'} · {layout.site.location or layout.site.name.split(' ')[0]}"
        return {"area_key": key, "fields": len(layout.zones), "area_ha": area, "water_m3": water, "moisture": moist,
                "index": index, "ndvi": ndvi, "alerts": alerts.get("open", 0)}

    def overview(self) -> dict:
        min_farms = int(self.settings.regional_min_farms)
        groups: dict[str, list[dict]] = {}
        for company in self.main.company_names():
            try:
                f = self._farm(company)
            except Exception:
                f = None
            if f:
                groups.setdefault(f["area_key"], []).append(f)
        areas = []
        for key, farms in sorted(groups.items()):
            if len(farms) < min_farms:
                areas.append({"area": key, "farms": len(farms), "suppressed": True})
                continue
            area = sum(f["area_ha"] for f in farms)
            water = sum(f["water_m3"] for f in farms)
            moist = [m for f in farms for m in f["moisture"]]
            idx = [s for f in farms for s in f["index"]]
            ndvi = [v for f in farms for v in f["ndvi"]]
            areas.append({"area": key, "farms": len(farms), "suppressed": False, "fields": sum(f["fields"] for f in farms),
                          "area_ha": round(area, 1), "water_month_m3": round(water), "water_month_mm": round(water / (area * 10), 1) if area else None,
                          "moisture_mean": round(sum(moist) / len(moist), 1) if moist else None,
                          "under_share": round(idx.count("under") / len(idx), 2) if idx else None,
                          "over_share": round(idx.count("over") / len(idx), 2) if idx else None,
                          "ndvi_mean": round(sum(ndvi) / len(ndvi), 3) if ndvi else None,
                          "open_alerts": sum(f["alerts"] for f in farms)})
        shown = [a for a in areas if not a["suppressed"]]
        return {"month": date.today().strftime("%Y-%m"), "min_farms": min_farms, "areas": areas,
                "totals": {"areas": len(areas), "farms": sum(a["farms"] for a in areas),
                           "area_ha": round(sum(a.get("area_ha") or 0 for a in shown), 1),
                           "water_month_m3": round(sum(a.get("water_month_m3") or 0 for a in shown))}}
