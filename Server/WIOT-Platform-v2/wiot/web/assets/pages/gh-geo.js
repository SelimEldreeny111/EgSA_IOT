// Greenhouse layout geometry (Track G): pure functions, no DOM and no Leaflet, so they can be
// tested with plain node. Polygons are arrays of [lat, lon] corners (not closed: the last corner
// joins the first). Metric work happens in a local equirectangular frame around the shape, the
// same approximation the server uses for areas and "extends outside" warnings (greenhouses are
// a few hundred metres at most, where it is accurate to millimetres).

const M_LAT = 110540;                      // metres per degree of latitude
const M_LON = 111320;                      // metres per degree of longitude at the equator
const RAD = Math.PI / 180;

/** Coordinates are stored with 7 decimals (about 1 cm), as the server rounds them. */
export const round7 = (v) => Math.round(v * 1e7) / 1e7;
export const roundPt = (p) => [round7(p[0]), round7(p[1])];

// ------------------------------------------------------------------ local frame
/** Origin of the local frame: the mean of the corners (as the server does). */
export function frame(points) {
  let lat = 0, lon = 0;
  for (const p of points) { lat += p[0]; lon += p[1]; }
  const lat0 = lat / points.length, lon0 = lon / points.length;
  return { lat0, lon0, kx: M_LON * Math.cos(lat0 * RAD), ky: M_LAT };
}

/** [lat, lon] corners -> [x, y] metres (x east, y north). */
export function toLocal(points, f = frame(points)) {
  return points.map((p) => [(p[1] - f.lon0) * f.kx, (p[0] - f.lat0) * f.ky]);
}

/** [x, y] metres -> [lat, lon] corners, rounded to 7 decimals. */
export function fromLocal(xy, f) {
  return xy.map((p) => [round7(f.lat0 + p[1] / f.ky), round7(f.lon0 + p[0] / f.kx)]);
}

const rotate = (xy, a) => {
  const c = Math.cos(a), s = Math.sin(a);
  return xy.map(([x, y]) => [x * c - y * s, x * s + y * c]);
};

// --------------------------------------------------------------------- measures
/** Signed shoelace area of [x, y] points (positive when counter-clockwise). */
function signedArea(xy) {
  let a = 0;
  for (let i = 0, n = xy.length; i < n; i++) {
    const p = xy[i], q = xy[(i + 1) % n];
    a += p[0] * q[1] - q[0] * p[1];
  }
  return a / 2;
}

/** Area in m² of a [lat, lon] polygon. */
export function area(poly) {
  return poly.length < 3 ? 0 : Math.abs(signedArea(toLocal(poly)));
}

/** Length in metres between two [lat, lon] points. */
export function distance(a, b) {
  const f = frame([a, b]);
  const [p, q] = toLocal([a, b], f);
  return Math.hypot(q[0] - p[0], q[1] - p[1]);
}

/** Area-weighted centre of a polygon (the corner mean for a degenerate one). */
export function centroid(poly) {
  const f = frame(poly), xy = toLocal(poly, f);
  const a = signedArea(xy);
  if (Math.abs(a) < 1e-9) return [f.lat0, f.lon0];
  let cx = 0, cy = 0;
  for (let i = 0, n = xy.length; i < n; i++) {
    const p = xy[i], q = xy[(i + 1) % n], k = p[0] * q[1] - q[0] * p[1];
    cx += (p[0] + q[0]) * k;
    cy += (p[1] + q[1]) * k;
  }
  return fromLocal([[cx / (6 * a), cy / (6 * a)]], f)[0];
}

/** [[south, west], [north, east]] of a polygon. */
export function bounds(poly) {
  let s = Infinity, w = Infinity, n = -Infinity, e = -Infinity;
  for (const p of poly) { s = Math.min(s, p[0]); n = Math.max(n, p[0]); w = Math.min(w, p[1]); e = Math.max(e, p[1]); }
  return [[s, w], [n, e]];
}

/** Ray casting: is [a, b] inside the polygon (works for [lat, lon] and for [x, y] alike). */
export function pointInPolygon(pt, poly) {
  const x = pt[0], y = pt[1];
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function distToEdges(pt, xy) {
  let best = Infinity;
  for (let i = 0, n = xy.length; i < n; i++) {
    const [x1, y1] = xy[i], [x2, y2] = xy[(i + 1) % n], dx = x2 - x1, dy = y2 - y1;
    const len = dx * dx + dy * dy;
    const t = len === 0 ? 0 : Math.max(0, Math.min(1, ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / len));
    best = Math.min(best, Math.hypot(pt[0] - (x1 + t * dx), pt[1] - (y1 + t * dy)));
  }
  return best;
}

/** A test "does this child polygon lie inside the parent" with the server's 0.5 m tolerance.
 *  The parent's frame is computed once, so checking thousands of benches stays cheap. */
export function container(parent, toleranceM = 0.5) {
  const f = frame(parent), pxy = toLocal(parent, f);
  return (child) => toLocal(child, f).every((p) => pointInPolygon(p, pxy) || distToEdges(p, pxy) <= toleranceM);
}
export const contained = (child, parent, toleranceM = 0.5) => container(parent, toleranceM)(child);

/** Move a polygon by a latitude/longitude offset. */
export function translate(poly, dLat, dLon) {
  return poly.map((p) => [round7(p[0] + dLat), round7(p[1] + dLon)]);
}

/** Midpoint of two [lat, lon] points (fine at greenhouse scale). */
export const midpoint = (a, b) => [round7((a[0] + b[0]) / 2), round7((a[1] + b[1]) / 2)];

// --------------------------------------------------------------------- drawing
/** Rectangle from three clicks: A and B are the ends of one wall (any rotation); C sets the width,
 *  the perpendicular distance from line AB, on C's side. Returns 4 corners, or null when A = B. */
export function rect3(A, B, C) {
  const f = frame([A, B, C]);
  const [a, b, c] = toLocal([A, B, C], f);
  const ux = b[0] - a[0], uy = b[1] - a[1], len = Math.hypot(ux, uy);
  if (len < 1e-6) return null;
  const nx = -uy / len, ny = ux / len;                       // unit normal of AB
  const d = (c[0] - a[0]) * nx + (c[1] - a[1]) * ny;        // signed width
  return fromLocal([a, b, [b[0] + nx * d, b[1] + ny * d], [a[0] + nx * d, a[1] + ny * d]], f);
}

/** Direction (radians, local frame: 0 = east, counter-clockwise) of the polygon's longest wall. */
export function longestEdgeAngle(poly) {
  return edgeAngle(toLocal(poly));
}
function edgeAngle(xy) {
  let best = -1, angle = 0;
  for (let i = 0, n = xy.length; i < n; i++) {
    const p = xy[i], q = xy[(i + 1) % n], len = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (len > best + 1e-9) { best = len; angle = Math.atan2(q[1] - p[1], q[0] - p[0]); }
  }
  return angle;
}

/** Do two segments cross (touching end to end does not count)? */
function segmentsCross(p1, p2, p3, p4) {
  const d = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const d1 = d(p3, p4, p1), d2 = d(p3, p4, p2), d3 = d(p1, p2, p3), d4 = d(p1, p2, p4);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

/** True when two walls of the polygon cross each other (corners clicked out of order). */
export function selfIntersects(poly) {
  const xy = toLocal(poly), n = xy.length;
  for (let i = 0; i < n; i++) {
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue;                  // neighbours through the closing wall
      if (segmentsCross(xy[i], xy[(i + 1) % n], xy[j], xy[(j + 1) % n])) return true;
    }
  }
  return false;
}

// ------------------------------------------------------------------ bench rows
/** Inside intervals [[x1, x2], ...] of the polygon along the horizontal line y. */
function scan(xy, y) {
  const xs = [];
  for (let i = 0, n = xy.length; i < n; i++) {
    const [x1, y1] = xy[i], [x2, y2] = xy[(i + 1) % n];
    if ((y1 > y) !== (y2 > y)) xs.push(x1 + ((y - y1) * (x2 - x1)) / (y2 - y1));
  }
  xs.sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i + 1 < xs.length; i += 2) out.push([xs[i], xs[i + 1]]);
  return out;
}

function intersect(a, b) {
  const out = [];
  for (let i = 0, j = 0; i < a.length && j < b.length;) {
    const lo = Math.max(a[i][0], b[j][0]), hi = Math.min(a[i][1], b[j][1]);
    if (hi > lo) out.push([lo, hi]);
    if (a[i][1] < b[j][1]) i++; else j++;
  }
  return out;
}

/** x intervals where the whole band ya..yb lies inside the polygon. The band is cut at the band's
 *  edges and at every corner height in between (just above and below). Between two neighbouring
 *  cuts no corner lies, so the same walls cross both lines in the same order: the k-th inside
 *  interval below and the k-th above bound one trapezoid, and x stays inside all the way up only
 *  where both hold. (Intersecting the two lines' interval sets is not enough: a slanted slot can
 *  pass x between them, leaving x inside one interval below and another one above.) */
function bandIntervals(xy, ya, yb) {
  const ys = [ya, yb];
  for (const p of xy) if (p[1] > ya && p[1] < yb) ys.push(p[1] - 1e-7, p[1] + 1e-7);
  ys.sort((a, b) => a - b);
  let prev = scan(xy, ys[0]), acc = prev;
  for (let i = 1; i < ys.length && acc.length; i++) {
    const cur = scan(xy, ys[i]);
    const sub = cur.length === prev.length
      ? prev.map((a, k) => [Math.max(a[0], cur[k][0]), Math.min(a[1], cur[k][1])]).filter(([lo, hi]) => hi > lo)
      : intersect(prev, cur);                        // a corner in between opens or closes an interval
    acc = intersect(acc, sub);
    prev = cur;
  }
  return acc;
}

function boxOf(xy) {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const [x, y] of xy) { x1 = Math.min(x1, x); x2 = Math.max(x2, x); y1 = Math.min(y1, y); y2 = Math.max(y2, y); }
  return [x1, y1, x2, y2];
}

/** Do two [x, y] polygons overlap (sharing only an edge does not count)? */
function overlapXY(a, b) {
  for (let i = 0; i < a.length; i++) {
    for (let j = 0; j < b.length; j++) {
      if (segmentsCross(a[i], a[(i + 1) % a.length], b[j], b[(j + 1) % b.length])) return true;
    }
  }
  return pointInPolygon(a[0], b) || pointInPolygon(b[0], a);
}

/**
 * Benches in parallel rows inside a zone.
 * opts: width (m, bench width), path (m, walkway between benches), margin (m, from the zone edge),
 *       direction "along" (benches parallel to the zone's longest wall) or "across",
 *       minLength (m, shorter pieces are dropped), avoid (polygons to keep clear of, e.g. the
 *       existing benches), max (most benches returned).
 * The zone is rotated so the chosen wall is horizontal; strips of the bench width are swept across
 * it (centred, with the path between them); in each strip a bench is as long as fits inside the
 * zone with the margin on all sides (one strip can hold several benches in an L- or U-shaped zone).
 * Returns rectangles as [lat, lon] corners.
 */
export function benchRows(zone, opts = {}) {
  const { width = 1.6, path = 0.8, margin = 0.5, direction = "along", minLength = 1, avoid = [], max = 1000 } = opts;
  if (!(width > 0) || !(path >= 0) || !(margin >= 0) || zone.length < 3) return [];
  const f = frame(zone);
  const angle = edgeAngle(toLocal(zone, f)) + (direction === "across" ? Math.PI / 2 : 0);
  const xy = rotate(toLocal(zone, f), -angle);
  const [, ymin, , ymax] = boxOf(xy);
  const usable = ymax - ymin - 2 * margin;
  if (usable < width) return [];
  const n = Math.floor((usable + path) / (width + path) + 1e-9);
  const used = n * width + (n - 1) * path;
  const keepOut = avoid.map((p) => {
    const r = rotate(toLocal(p, f), -angle);
    return { xy: r, box: boxOf(r) };
  });
  const out = [];
  let y = ymin + margin + (usable - used) / 2;
  for (let i = 0; i < n && out.length < max; i++, y += width + path) {
    for (const [x1, x2] of bandIntervals(xy, y - margin, y + width + margin)) {
      const a = x1 + margin, b = x2 - margin;
      if (b - a < minLength) continue;
      const rect = [[a, y], [b, y], [b, y + width], [a, y + width]];
      if (keepOut.length) {
        const inner = [[a + 0.01, y + 0.01], [b - 0.01, y + 0.01], [b - 0.01, y + width - 0.01], [a + 0.01, y + width - 0.01]];
        const clash = keepOut.some((k) => k.box[0] < b && k.box[2] > a && k.box[1] < y + width && k.box[3] > y && overlapXY(inner, k.xy));
        if (clash) continue;
      }
      out.push(rect);
      if (out.length >= max) break;
    }
  }
  return out.map((r) => fromLocal(rotate(r, angle), f));
}
