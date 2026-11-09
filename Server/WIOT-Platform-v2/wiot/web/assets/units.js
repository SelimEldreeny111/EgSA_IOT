// Unit system per company (Organization → company profile): metric or US customary.
// Values are stored and computed in SI; conversion happens only at display time.
import { fmtNum } from "./charts.js";

export const UNITS = { system: "metric" };

const TABLE = {
  flow: { metric: [1, "m³/h"], imperial: [4.402868, "gpm"] },        // US gallons per minute
  volume: { metric: [1, "m³"], imperial: [264.172052, "gal"] },      // US gallons
  area: { metric: [1, "ha"], imperial: [2.471054, "ac"] },
  temp: { metric: [null, "°C"], imperial: [null, "°F"] },
  depth: { metric: [1, "mm"], imperial: [1 / 25.4, "in"] },
  speed: { metric: [1, "km/h"], imperial: [0.621371, "mph"] },
  length: { metric: [1, "m"], imperial: [3.28084, "ft"] },
};

export const imperial = () => UNITS.system === "imperial";

/** Convert an SI value of the given kind into the active unit system. */
export function conv(v, kind) {
  if (v === null || v === undefined || Number.isNaN(+v)) return v;
  if (kind === "temp") return imperial() ? (+v * 9) / 5 + 32 : +v;
  const row = TABLE[kind];
  return row ? +v * row[imperial() ? "imperial" : "metric"][0] : +v;
}

/** Inverse of ``conv``: a value typed in display units back to SI. */
export function toSI(v, kind) {
  if (v === null || v === undefined || v === "" || Number.isNaN(+v)) return v;
  if (kind === "temp") return imperial() ? ((+v - 32) * 5) / 9 : +v;
  const row = TABLE[kind];
  return row ? +v / row[imperial() ? "imperial" : "metric"][0] : +v;
}

export const unit = (kind) => TABLE[kind]?.[imperial() ? "imperial" : "metric"][1] ?? "";

/** "12.5 m³/h" / "55.0 gpm" — number and unit. */
export function fmtU(v, kind, d = 1) {
  if (v === null || v === undefined || Number.isNaN(+v)) return "–";
  return `${fmtNum(conv(v, kind), d)} ${unit(kind)}`;
}

/** Same as fmtU but with the unit in a <small> (KPI tiles, map chips). */
export function fmtUs(v, kind, d = 1) {
  if (v === null || v === undefined || Number.isNaN(+v)) return "–";
  return `${fmtNum(conv(v, kind), d)}<small>${unit(kind)}</small>`;
}
