// Stage 3 maths: lock the AI's relative depth to the camera solve (port of src/vid3d/depth.py).
import { Rng, median } from "./linalg.js";

export interface Fit { a: number; b: number; inliers: number }

/** Fit 1/z = a*disp + b robustly (Theil-Sen start, then IRLS with MAD). Null when the fit is not trustworthy. */
export function alignDisparity(disp: Float64Array, z: Float64Array, iters = 3): Fit | null {
  const n = z.length;
  if (n < 20) return null;
  const target = new Float64Array(n);
  for (let i = 0; i < n; i++) target[i] = 1 / z[i];
  const rng = new Rng(0), slopes: number[] = [];
  for (let k = 0; k < 2000; k++) {
    const i = rng.int(n), j = rng.int(n), dd = disp[i] - disp[j];
    if (Math.abs(dd) > 1e-9) slopes.push((target[i] - target[j]) / dd);
  }
  if (slopes.length < 10) return null;
  let a = median(slopes);
  const off = new Float64Array(n);
  for (let i = 0; i < n; i++) off[i] = target[i] - a * disp[i];
  let b = median(off);
  const res = new Float64Array(n), keep = new Uint8Array(n);
  const residuals = () => { for (let i = 0; i < n; i++) res[i] = Math.abs(a * disp[i] + b - target[i]); };
  residuals();
  let cut = 3 * 1.4826 * (median(res) + 1e-12), kept = 0;
  for (let i = 0; i < n; i++) { keep[i] = res[i] < cut ? 1 : 0; kept += keep[i]; }
  for (let it = 0; it < iters; it++) {
    // ordinary least squares on the kept points: minimise sum (a d + b - t)^2
    let sd = 0, st = 0, sdd = 0, sdt = 0, m = 0;
    for (let i = 0; i < n; i++) if (keep[i]) { sd += disp[i]; st += target[i]; sdd += disp[i] * disp[i]; sdt += disp[i] * target[i]; m++; }
    const den = m * sdd - sd * sd;
    if (Math.abs(den) < 1e-300) return null;
    a = (m * sdt - sd * st) / den;
    b = (st - a * sd) / m;
    residuals();
    const inRes: number[] = [];
    for (let i = 0; i < n; i++) if (keep[i]) inRes.push(res[i]);
    cut = 3 * 1.4826 * (median(inRes) + 1e-12);
    kept = 0;
    for (let i = 0; i < n; i++) { keep[i] = res[i] < cut ? 1 : 0; kept += keep[i]; }
    if (kept < 15) return null;
  }
  if (a <= 0) return null;
  return { a, b, inliers: kept / n };
}

/** Disparity -> depth (float32, NaN where unreliable or on depth edges: the "flying pixel" filter). */
export function metricDepth(disp: Float32Array, h: number, w: number, a: number, b: number, zMin: number, zMax: number): Float32Array {
  const depth = new Float32Array(h * w).fill(NaN);
  for (let i = 0; i < h * w; i++) {
    const inv = a * disp[i] + b;
    if (inv > 1e-6) { const d = Math.fround(1 / inv); if (!(d < zMin || d > zMax)) depth[i] = d; }
  }
  const out = new Float32Array(depth);
  // np.gradient: central differences inside, one-sided at the borders
  const gx = (y: number, x: number) => (x === 0 ? depth[y * w + 1] - depth[y * w] : x === w - 1 ? depth[y * w + x] - depth[y * w + x - 1]
    : (depth[y * w + x + 1] - depth[y * w + x - 1]) / 2);
  const gy = (y: number, x: number) => (y === 0 ? depth[w + x] - depth[x] : y === h - 1 ? depth[y * w + x] - depth[(y - 1) * w + x]
    : (depth[(y + 1) * w + x] - depth[(y - 1) * w + x]) / 2);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    if (w < 2 || h < 2) break;
    const rel = Math.hypot(gx(y, x), gy(y, x)) / depth[i];
    if (!(rel < 0.04)) out[i] = NaN;
  }
  return out;
}
