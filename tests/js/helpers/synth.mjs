// An analytic box room (4 x 5 x 2.6 m) rendered to depth, "AI disparity" and sparse SfM points, for testing the whole port without a model.
import { Rng } from "../../../viewer/js/core/linalg.js";

const SCALE = 0.3; // the reconstruction's arbitrary units: everything is 0.3 of a metre
export const ROOM = { x: 4, y: 2.6, z: 5, camHeight: 1.5 };

const sub = (a, b) => a.map((v, i) => v - b[i]), dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a) => { const n = Math.hypot(...a); return a.map((v) => v / n); };

function pose(c, yaw, pitch) {
  const f = [Math.cos(pitch) * Math.sin(yaw), -Math.sin(pitch), Math.cos(pitch) * Math.cos(yaw)];
  const r = unit(cross(f, [0, 1, 0])), d = cross(f, r);
  const R = [...r, ...d, ...f];
  return { R, t: [-dot(r, c), -dot(d, c), -dot(f, c)], f, r, d };
}

const COLORS = { floor: [150, 120, 90], ceil: [235, 235, 230], x0: [190, 70, 60], x1: [70, 110, 190], z0: [200, 190, 120], z1: [90, 160, 110] };

/** Depth along the optical axis (metres) and the surface hit, for a ray from c along dir (inside the box). */
function cast(c, dir) {
  let best = { s: Infinity, id: null };
  const planes = [["x0", 0, 0], ["x1", 0, ROOM.x], ["floor", 1, 0], ["ceil", 1, ROOM.y], ["z0", 2, 0], ["z1", 2, ROOM.z]];
  for (const [id, axis, v] of planes) {
    if (Math.abs(dir[axis]) < 1e-9) continue;
    const s = (v - c[axis]) / dir[axis];
    if (s > 1e-6 && s < best.s) best = { s, id };
  }
  return best;
}

export function makeRoom({ frames = 24, w = 800, h = 600, focal = 570, seed = 1 } = {}) {
  const rng = new Rng(seed), center = [2, ROOM.camHeight, 2.5], payloadFrames = [], images = [];
  for (let i = 0; i < frames; i++) {
    const a = (i / frames) * 2 * Math.PI, c = [center[0] + 0.9 * Math.cos(a), ROOM.camHeight + 0.03 * Math.sin(3 * a), center[2] + 1.2 * Math.sin(a)];
    const p = pose(c, a + 1.2, 0.25);
    const disp = new Float32Array(w * h), rgb = new Uint8Array(w * h * 3), zmap = new Float64Array(w * h);
    for (let v = 0; v < h; v++) for (let u = 0; u < w; u++) {
      const x = (u + 0.5 - w / 2) / focal, y = (v + 0.5 - h / 2) / focal;
      const dir = unit([x * p.r[0] + y * p.d[0] + p.f[0], x * p.r[1] + y * p.d[1] + p.f[1], x * p.r[2] + y * p.d[2] + p.f[2]]);
      const hit = cast(c, dir), z = hit.s * dot(dir, p.f);
      zmap[v * w + u] = z;
      disp[v * w + u] = ((1 / (z * SCALE)) - 0.05) / 1.7 + rng.normal(0.0005); // "the AI": relative inverse depth, unknown affine
      rgb.set(COLORS[hit.id].map((q) => q + Math.round(rng.normal(3))), (v * w + u) * 3);
    }
    const obs = [];
    for (let k = 0; k < 600; k++) {
      const u = rng.int(w), v = rng.int(h), z = zmap[v * w + u] * SCALE * (rng.next() < 0.05 ? rng.uniform(0.5, 2) : 1 + rng.normal(0.01));
      obs.push([u + 0.5, v + 0.5, z]);
    }
    const cs = c.map((q) => q * SCALE);
    const t = [-dot(p.R.slice(0, 3), cs), -dot(p.R.slice(3, 6), cs), -dot(p.R.slice(6, 9), cs)];
    payloadFrames.push({ name: `frame_${String(i).padStart(4, "0")}.jpg`, R: p.R, t, obs });
    images.push({ rgb, disp });
  }
  const payload = { version: 1, camera: { width: w, height: h, focal, cx: w / 2, cy: h / 2, k1: 0 }, frames_total: frames, reprojection_error_px: 0.3, frames: payloadFrames };
  const source = { luma: (i) => 110 + (i % 5) * 4, frame: (i) => images[i] };
  return { payload, source, w, h };
}
