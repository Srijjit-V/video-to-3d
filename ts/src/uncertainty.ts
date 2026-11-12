// How wrong could the numbers be? Port of src/vid3d/uncertainty.py (derivation: docs/MATH.md). Output keys match scene.json.
import { analyze, extent, wallPoints, type Room } from "./floorplan.js";
import { roundTo } from "./color.js";
import type { FloorInfo } from "./geometry.js";
import { Rng, mean, median, percentiles, std } from "./linalg.js";

export const SCALE_SIGMA_REL: Record<string, number> = { assumed: 0.08, given: 0.03, ceiling: 0.02 };
export const THRESHOLD_RANGE: [number, number] = [0.15, 0.45];
export const CAMERA_HEIGHT_RELATIVE_LIMIT = 0.15;
export const MAX_WALL_POINTS = 6000;

export type Range = [number, number | null];

export function scaleSource(method: string): "ceiling" | "assumed" | "given" {
  if (method.startsWith("ceiling height =")) return "ceiling";
  return method.includes("(assumed)") ? "assumed" : "given";
}

const interval = (values: Float64Array, digits: number): [number, number] => { const [lo, hi] = percentiles(values, [5, 95]); return [roundTo(lo, digits), roundTo(hi, digits)]; };

/** '3.8 to 4.2 m', or 'at least 2.7 m' when there is no upper end. */
export const formatRange = (r: Range, unit: string): string => (r[1] === null ? `at least ${r[0]} ${unit}` : `${r[0]} to ${r[1]} ${unit}`);

export function areaHalfWidthRel(ranges: { area_m2: Range } | null): number | null {
  if (!ranges || ranges.area_m2[1] === null) return null;
  const [lo, hi] = ranges.area_m2 as [number, number];
  return (hi - lo) / 2 / Math.max(1e-9, (hi + lo) / 2);
}

export interface Estimate {
  scale_source: string; scale_sigma_rel: number; samples: number;
  central: Record<string, number | null | undefined> | null;
  ranges: { length_m: Range; width_m: Range; area_m2: Range; height_m: Range | null; [k: string]: Range | null } | null;
  lower_bound_only?: string[];
}

/** Central values and 90% ranges for the room (Monte Carlo over scale error, wall bootstrap and wall threshold). */
export function estimate(points: ArrayLike<number>, roomHeight: number | null, method: string, floorSigmaRel: number, n = 400, seed = 0): Estimate {
  const room = analyze(points, roomHeight), src = scaleSource(method), sigma = Math.hypot(SCALE_SIGMA_REL[src], floorSigmaRel);
  const out: Estimate = { scale_source: src, scale_sigma_rel: roundTo(sigma, 3), samples: n, central: null, ranges: null };
  if (!room.length_m || room.incomplete) return out;
  const rng = new Rng(seed);
  let xz = wallPoints(points, roomHeight), m = xz.length / 2;
  if (m > MAX_WALL_POINTS) {
    const pick = rng.choice(m, MAX_WALL_POINTS), s = new Float64Array(2 * MAX_WALL_POINTS);
    pick.forEach((p, i) => { s[2 * i] = xz[2 * p]; s[2 * i + 1] = xz[2 * p + 1]; });
    xz = s; m = MAX_WALL_POINTS;
  }
  const lengths = new Float64Array(n), widths = new Float64Array(n), sx = new Float64Array(m), sz = new Float64Array(m);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < m; j++) { const p = rng.int(m); sx[j] = xz[2 * p]; sz[j] = xz[2 * p + 1]; }
    const frac = rng.uniform(THRESHOLD_RANGE[0], THRESHOLD_RANGE[1]);
    const [x0, x1] = extent(sx, frac), [z0, z1] = extent(sz, frac);
    lengths[i] = x1 - x0; widths[i] = z1 - z0;
  }
  const f = new Float64Array(n);
  for (let i = 0; i < n; i++) f[i] = Math.min(2, Math.max(0.5, (1 + rng.normal(SCALE_SIGMA_REL[src])) / (1 + rng.normal(floorSigmaRel))));
  const L = lengths.map((v, i) => v * f[i]), W = widths.map((v, i) => v * f[i]);
  const ranges: NonNullable<Estimate["ranges"]> = {
    length_m: interval(L, 2), width_m: interval(W, 2), area_m2: interval(L.map((v, i) => v * W[i]), 1),
    height_m: roomHeight ? interval(f.map((v) => roomHeight * v), 2) : null,
  };
  if (room.missing_wall) {
    const axis = room.missing_axis as string;
    ranges[axis] = [(ranges[axis] as [number, number])[0], null];
    ranges.area_m2 = [ranges.area_m2[0], null];
    out.lower_bound_only = [axis, "area_m2"];
  }
  out.central = { length_m: room.length_m, width_m: room.width_m, area_m2: room.area_m2, height_m: room.height_m ?? null };
  out.ranges = ranges;
  return out;
}

/** Relative spread of the fitted camera height when the floor is re-fitted on random halves of the cloud. */
export function floorSigmaRel(findFloor: (p: ArrayLike<number>, c: ArrayLike<number>, up: number[]) => FloorInfo, points: ArrayLike<number>,
  cams: ArrayLike<number>, upHint: number[], draws = 12, seed = 0, fraction = 0.5): number {
  const rng = new Rng(seed), np = Math.floor(points.length / 3), heights: number[] = [];
  for (let d = 0; d < draws; d++) {
    const take = rng.choice(np, Math.min(40000, Math.max(100, Math.floor(fraction * np)))), sub = new Float64Array(take.length * 3);
    take.forEach((p, i) => { sub[3 * i] = points[3 * p]; sub[3 * i + 1] = points[3 * p + 1]; sub[3 * i + 2] = points[3 * p + 2]; });
    try { heights.push(findFloor(sub, cams, upHint).camHeightRaw); } catch { /* the floor was not found on this subset */ }
  }
  return heights.length < 3 ? 0.05 : std(heights) / Math.abs(mean(heights));
}

export function cameraHeightConsistency(heights: ArrayLike<number>) {
  const med = median(heights), spread = std(heights), rel = med > 0 ? spread / med : 1;
  return { median_m: roundTo(med, 3), spread_m: roundTo(spread, 3), relative: roundTo(rel, 3), inconsistent: rel > CAMERA_HEIGHT_RELATIVE_LIMIT };
}

export interface Confidence { score: number; label: "high" | "medium" | "low"; summary: string; reasons: string[] }

/** A 0 to 100 score with the reasons, in words. High 75+, medium 50 to 74, low below. */
export function confidence(method: string, registeredShare: number, room: Room, areaHalfWidth: number | null, heightInconsistent: boolean): Confidence {
  let score = 100; const reasons: string[] = [], src = scaleSource(method);
  if (src === "assumed") { score -= 25; reasons.push("Real-world scale is a guess from typical phone height."); }
  else if (src === "given") { score -= 10; reasons.push("Scale depends on the camera height you gave."); }
  else { score -= 5; reasons.push("Scale comes from the ceiling height you gave."); }
  if (registeredShare < 0.8) { score -= Math.min(25, (0.8 - registeredShare) * 100); reasons.push(`Only ${Math.round(registeredShare * 100)}% of the frames could be placed.`); }
  if (room.incomplete) { score = Math.min(score, 20); reasons.push("Opposite walls were not both captured, so there is no size to trust."); }
  else if (room.missing_wall) { score = Math.min(score, 35); reasons.push("A wall was never filmed, so the room is bigger than what was measured."); }
  else if (room.rectangular === false) { score -= 20; reasons.push("The outline is not a simple rectangle, so the area is an upper bound."); }
  if (areaHalfWidth !== null) {
    if (areaHalfWidth > 0.25) { score -= 30; reasons.push("The area range is very wide."); }
    else if (areaHalfWidth > 0.15) { score -= 15; reasons.push("The area range is fairly wide."); }
  }
  if (heightInconsistent) { score -= 10; reasons.push("The phone height changed a lot during the walk, so one scale fits less well."); }
  score = Math.max(0, Math.min(100, Math.round(score)));
  const label = score >= 75 ? "high" : score >= 50 ? "medium" : "low";
  const summary = { high: "You can rely on these sizes within the ranges shown.",
    medium: "Good for planning. Calibrate with something you measured before relying on exact values.", low: "Treat these as a rough idea only." }[label];
  return { score, label, summary, reasons };
}
