// Top-down analysis (port of src/vid3d/floorplan.py, without the PNG drawing): wall alignment, room size, wall support, palette.
// Input points are metric, floor at y = 0, +y up. Output objects use the same keys as scene.json.
import { dominantColors, roundTo, type Swatch } from "./color.js";
import { yawAlign } from "./geometry.js";
import { Rng, arange, histogramEdges, histogramRange, mean, percentiles } from "./linalg.js";

export const CELL = 0.05;
export const MIN_WALL_SUPPORT = 0.88;
export const MISSING_WALL_SIDE = 0.3;
export const MIN_ROOM_SIDE_M = 1.0;
export const STRONG_FRAC = 0.3;

export interface Room {
  rect_m?: number[]; rectangular?: boolean; wall_support?: number; missing_wall?: boolean; missing_axis?: string | null;
  area_is_upper_bound?: boolean; area_is_lower_bound?: boolean; length_m?: number; width_m?: number; height_m?: number | null;
  area_m2?: number; area_ft2?: number; incomplete?: boolean; reason?: string; at_least_m?: number[];
}

/** Flat [x, z, x, z, ...] of points between knee and head height (below the ceiling when its height is known). */
export function wallPoints(points: ArrayLike<number>, roomHeight: number | null): Float64Array {
  const top = roomHeight ? roomHeight - 0.2 : 2.1, out: number[] = [];
  for (let i = 0; i < points.length; i += 3) { const y = points[i + 1]; if (y > 0.3 && y < top) out.push(points[i], points[i + 2]); }
  return Float64Array.from(out);
}

const column = (xz: Float64Array, k: number): Float64Array => { const c = new Float64Array(xz.length / 2); for (let i = 0; i < c.length; i++) c[i] = xz[2 * i + k]; return c; };

/** Angle (deg) that makes the walls line up with the x/z axes (maximises the sum of squared histogram counts). */
export function dominantYaw(points: ArrayLike<number>, roomHeight: number | null): number {
  let xz = wallPoints(points, roomHeight), n = xz.length / 2;
  if (n < 100) return 0;
  if (n > 40000) { const pick = new Rng(0).choice(n, 40000), s = new Float64Array(80000); pick.forEach((p, i) => { s[2 * i] = xz[2 * p]; s[2 * i + 1] = xz[2 * p + 1]; }); xz = s; n = 40000; }
  let mx = 0, mz = 0;
  for (let i = 0; i < n; i++) { mx += xz[2 * i] / n; mz += xz[2 * i + 1] / n; }
  for (let i = 0; i < n; i++) { xz[2 * i] -= mx; xz[2 * i + 1] -= mz; }
  const peakiness = (deg: number) => {
    const r = yawAlign(xz, -deg);
    let score = 0;
    for (let k = 0; k < 2; k++) {
      const c = column(r, k); let lo = Infinity, hi = -Infinity;
      for (const v of c) { if (v < lo) lo = v; if (v > hi) hi = v; }
      for (const h of histogramEdges(c, arange(lo, hi + CELL, CELL / 2))) score += h * h;
    }
    return score;
  };
  const argmax = (xs: Float64Array) => { let b = 0, bs = -Infinity; xs.forEach((d, i) => { const s = peakiness(d); if (s > bs) { bs = s; b = i; } }); return xs[b]; };
  const best = argmax(arange(0, 90, 1));
  return argmax(arange(best - 1, best + 1.01, 0.1));
}

/** Room span along one axis: the outermost strong wall peaks in a 1-D histogram. */
export function extent(coord: Float64Array, frac = STRONG_FRAC): [number, number] {
  const [lo, hi] = percentiles(coord, [0.5, 99.5]);
  const edges = arange(lo - CELL, hi + 2 * CELL, CELL), h = histogramEdges(coord, edges);
  let mx = 0; for (const v of h) if (v > mx) mx = v;
  let first = -1, last = -1;
  h.forEach((v, i) => { if (v >= frac * mx) { if (first < 0) first = i; last = i; } });
  const loS = edges[first] + CELL / 2, hiS = edges[last] + CELL / 2;
  const [pLo, pHi] = percentiles(coord, [1, 99]);
  return hiS - loS < 0.5 * (pHi - pLo) ? [pLo, pHi] : [loS, hiS]; // one-wall peaks: use the trimmed spread instead
}

const roundHalfEven = (x: number): number => { const r = Math.round(x); return Math.abs(x % 1) === 0.5 && r % 2 ? r - 1 : r; };

/** For each side of the bounding rectangle, how much of it is backed by wall points (0 to 1). Order: x0, x1, z0, z1. */
export function sideSupport(xz: Float64Array, rect: number[]): number[] {
  const [x0, z0, x1, z1] = rect, near = 0.25, step = 0.1, scores: number[] = [], n = xz.length / 2;
  for (const [axis, fixed] of [[0, x0], [0, x1], [1, z0], [1, z1]] as const) {
    const [lo, hi] = axis === 0 ? [z0, z1] : [x0, x1], sel: number[] = [];
    for (let i = 0; i < n; i++) if (Math.abs(xz[2 * i + axis] - fixed) < near) sel.push(xz[2 * i + 1 - axis]);
    const bins = Math.max(1, roundHalfEven((hi - lo) / step)), h = histogramRange(sel, bins, lo, hi);
    scores.push(h.filter((v) => v > 0).length / bins);
  }
  return scores;
}

export const wallSupport = (xz: Float64Array, rect: number[]): number => mean(sideSupport(xz, rect));

/** Room size, wall support and flags from metric points. `frac` is the wall-peak threshold (default 0.3). */
export function analyze(points: ArrayLike<number>, roomHeight: number | null): Room {
  const xz = wallPoints(points, roomHeight);
  if (xz.length / 2 < 100) return {};
  const [x0, x1] = extent(column(xz, 0)), [z0, z1] = extent(column(xz, 1));
  const length = x1 - x0, width = z1 - z0;
  if (Math.min(length, width) < MIN_ROOM_SIDE_M) {
    return { incomplete: true, reason: "Opposite walls were not both captured, so the room size can't be measured.",
      at_least_m: [roundTo(Math.max(length, width), 2), roundTo(Math.min(length, width), 2)] };
  }
  const area = length * width, sides = sideSupport(xz, [x0, z0, x1, z1]), support = mean(sides);
  const rectangular = support >= MIN_WALL_SUPPORT, missing = !rectangular && Math.min(...sides) < MISSING_WALL_SIDE;
  return {
    rect_m: [x0, z0, x1, z1], rectangular, wall_support: roundTo(support, 3), missing_wall: missing,
    missing_axis: missing ? (sides.indexOf(Math.min(...sides)) < 2 ? "length_m" : "width_m") : null,
    area_is_upper_bound: !rectangular && !missing, area_is_lower_bound: missing,
    length_m: roundTo(length, 3), width_m: roundTo(width, 3), height_m: roomHeight ? roundTo(roomHeight, 3) : null,
    area_m2: roundTo(area, 2), area_ft2: roundTo(area * 10.7639, 1),
  };
}

/** Dominant colours of the walls, floor and ceiling, from the points on each surface. `colors` is flat RGB bytes. */
export function palette(points: ArrayLike<number>, colors: Uint8Array, room: Room, roomHeight: number | null): { floor: Swatch[]; ceiling: Swatch[]; walls: Swatch[] } {
  const n = points.length / 3, pick = (test: (i: number) => boolean): number[] => {
    const out: number[] = [];
    for (let i = 0; i < n; i++) if (test(i)) out.push(colors[3 * i], colors[3 * i + 1], colors[3 * i + 2]);
    return out;
  };
  const y = (i: number) => points[3 * i + 1];
  const floor = dominantColors(pick((i) => Math.abs(y(i)) < 0.06));
  const ceiling = roomHeight ? dominantColors(pick((i) => Math.abs(y(i) - roomHeight) < 0.08)) : [];
  let walls: Swatch[] = [];
  if (room.rect_m) {
    const [x0, z0, x1, z1] = room.rect_m, top = roomHeight ? roomHeight - 0.2 : 2.1;
    walls = dominantColors(pick((i) => {
      const near = Math.min(Math.abs(points[3 * i] - x0), Math.abs(points[3 * i] - x1), Math.abs(points[3 * i + 2] - z0), Math.abs(points[3 * i + 2] - z1)) < 0.15;
      return near && y(i) > 0.3 && y(i) < top;
    }));
  }
  return { floor, ceiling, walls };
}
