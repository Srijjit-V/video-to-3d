// Stages 3-6 in one place (port of src/vid3d/pipeline.py): from an sfm payload plus per-frame pictures and AI disparity
// to a metric point cloud and a scene.json-shaped object. Pure numbers in, numbers out: no DOM, so it runs in a worker or in Node.
import { exposureGains, normalizeFrame, roundTo } from "./color.js";
import { type FloorInfo, type View, backproject, findFloor, floorFrame, fuse, viewCenter, viewUp, yawAlign } from "./geometry.js";
import { alignDisparity, metricDepth } from "./depth.js";
import { analyze, dominantYaw, palette, type Room } from "./floorplan.js";
import { median, percentile } from "./linalg.js";
import { areaHalfWidthRel, cameraHeightConsistency, confidence, estimate, floorSigmaRel, formatRange } from "./uncertainty.js";

export const DEFAULT_CAMERA_HEIGHT_M = 1.45;
export const PAYLOAD_VERSION = 1;

export interface SfmPayload {
  version: number;
  camera: { width: number; height: number; focal: number; cx: number; cy: number; k1: number };
  frames_total: number;
  reprojection_error_px: number;
  frames: { name: string; R: number[]; t: number[]; obs: number[][] }[];
}

/** What the browser layer provides for each placed frame. `disp` is relative inverse depth at the frame's size (bigger = closer). */
export interface FrameSource {
  luma(i: number): Promise<number> | number;
  frame(i: number): Promise<{ rgb: Uint8Array; disp: Float32Array }> | { rgb: Uint8Array; disp: Float32Array };
}

export interface Options { cameraHeight?: number | null; ceilingHeight?: number | null; stride?: number; videoLabel?: string; secondsSoFar?: number;
  onProgress?: (stage: number, done: number, total: number) => void }

export interface BuiltScene { points: Float32Array; colors: Uint8Array; views: Uint8Array; scene: Record<string, unknown> }

const fail = (m: string): never => { throw new Error(m); };

/** The same sanity checks as src/vid3d/sfm_payload.py: the payload comes from outside the page. */
export function validatePayload(p: SfmPayload): void {
  const fin = (v: unknown) => typeof v === "number" && Number.isFinite(v);
  if (!p || p.version !== PAYLOAD_VERSION) fail(`unsupported sfm payload version (expected ${PAYLOAD_VERSION})`);
  const c = p.camera;
  if (!c || ![c.width, c.height, c.focal, c.cx, c.cy, c.k1].every(fin) || c.width <= 0 || c.height <= 0 || c.focal <= 0) fail("camera is malformed");
  if (!Array.isArray(p.frames) || p.frames.length < 1 || p.frames.length > 400) fail("frames must hold 1 to 400 entries");
  for (const f of p.frames) {
    if (!/^[A-Za-z0-9_.-]{1,64}\.jpg$/.test(f.name) || f.R?.length !== 9 || f.t?.length !== 3 || ![...f.R, ...f.t].every(fin)) fail("a frame pose is malformed");
    if (!Array.isArray(f.obs) || f.obs.length > 50000 || f.obs.some((o) => o.length !== 3 || !o.every(fin))) fail("observations are malformed");
  }
  if (!Number.isInteger(p.frames_total) || p.frames_total < p.frames.length) fail("frames_total must be at least the number of placed frames");
}

export function qualityWarnings(scene: { frames_registered: number; frames_extracted: number; frames_with_depth: number; room: Room;
  camera_height: { inconsistent: boolean }; scale_method: string }): string[] {
  const w: string[] = [], placed = scene.frames_registered / Math.max(1, scene.frames_extracted);
  if (placed < 0.8) w.push(`Only ${scene.frames_registered} of ${scene.frames_extracted} frames could be placed; parts of the room may be missing. Try a slower, steadier video.`);
  if (scene.frames_with_depth < 0.7 * scene.frames_registered) w.push("AI depth could not be matched on many frames; the model may be patchy.");
  if (scene.room.incomplete) w.push(scene.room.reason as string);
  if (scene.camera_height.inconsistent) w.push("The phone height changed a lot during the walk, so a single scale may not fit the whole room. Hold the phone at one height.");
  if (scene.room.missing_wall) w.push("One wall looks like it was never filmed, so the room may be bigger than measured. Walk so every wall appears at some point.");
  else if (scene.room.rectangular === false) w.push("The room outline is not a simple rectangle (an L-shaped room, or a wall that was only partly captured). The area shown is the bounding rectangle, so the real floor area is smaller.");
  if (scene.scale_method.includes("(assumed)")) w.push("Real-world scale is a guess from typical phone height (about ±5–10%). Use the camera height or ceiling height option, or calibrate in the viewer, to tighten it.");
  return w;
}

export async function buildScene(payload: SfmPayload, source: FrameSource, opts: Options = {}): Promise<BuiltScene> {
  validatePayload(payload);
  const t0 = Date.now(), stride = opts.stride ?? 4, progress = opts.onProgress ?? (() => {});
  const { width: W, height: H, focal, cx, cy, k1 } = payload.camera;
  const views: View[] = payload.frames.map((f) => ({ fx: focal, fy: focal, cx, cy, R: f.R, t: f.t }));
  const n = views.length;

  // stage 3: depth fitted to the sparse points, back-projected
  const lumas: number[] = [];
  for (let i = 0; i < n; i++) lumas.push(await source.luma(i));
  const gains = exposureGains(lumas);
  const P: number[] = [], C: number[] = [], F: number[] = [];
  const fits: number[] = [];
  for (let i = 0; i < n; i++) {
    const { rgb, disp } = await source.frame(i), obs = payload.frames[i].obs;
    progress(3, i + 1, n);
    if (obs.length < 20) continue;
    const ds = new Float64Array(obs.length), z = new Float64Array(obs.length);
    obs.forEach((o, j) => {
      const u = Math.min(W - 1, Math.max(0, Math.trunc(o[0]))), v = Math.min(H - 1, Math.max(0, Math.trunc(o[1])));
      ds[j] = disp[v * W + u]; z[j] = o[2];
    });
    const fit = alignDisparity(ds, z);
    if (!fit) continue;
    let zMin = Infinity; for (const v of z) if (v < zMin) zMin = v;
    const depth = metricDepth(disp, H, W, fit.a, fit.b, 0.5 * zMin, 2 * percentile(z, 98));
    const bp = backproject(views[i], depth, normalizeFrame(rgb, W * H, gains[i]), H, W, stride, k1);
    for (let j = 0; j < bp.points.length; j++) P.push(bp.points[j]);
    for (let j = 0; j < bp.colors.length; j++) C.push(bp.colors[j]);
    for (let j = 0; j < bp.points.length / 3; j++) F.push(i);
    fits.push(fit.inliers);
  }
  if (!P.length) fail("The AI depth could not be matched to the camera path on any frame. Try a video with more texture and steady lighting.");

  // stage 4: fuse (a point survives only if two frames agree)
  progress(4, 0, 1);
  const medianZ = median(payload.frames.flatMap((f) => f.obs.map((o) => o[2])));
  const fused = fuse(P, C, F, medianZ / 200, 2);
  let raw = fused.points;

  // stage 5: floor, scale, yaw
  progress(5, 0, 1);
  const cams = new Float64Array(n * 3);
  views.forEach((v, i) => cams.set(viewCenter(v), 3 * i));
  const upHint = [0, 0, 0];
  views.forEach((v) => viewUp(v).forEach((u, j) => { upHint[j] += u / n; }));
  const floor: FloorInfo = findFloor(raw, cams, upHint);
  const { Rw, origin } = floorFrame(floor, cams);
  let scale: number, method: string;
  if (opts.ceilingHeight && floor.ceilingHeightRaw) {
    scale = opts.ceilingHeight / floor.ceilingHeightRaw; method = `ceiling height = ${opts.ceilingHeight} m`;
  } else {
    const h = opts.cameraHeight || DEFAULT_CAMERA_HEIGHT_M;
    method = opts.cameraHeight ? `camera height given: ${h} m` : `camera held at ~${h} m above floor (assumed)`;
    scale = h / floor.camHeightRaw;
    if (opts.ceilingHeight) method += " (ceiling not detected, so the ceiling height was ignored)";
  }
  const toMetric = (X: ArrayLike<number>): Float32Array => {
    const out = new Float32Array(X.length);
    for (let i = 0; i < X.length; i += 3) for (let j = 0; j < 3; j++)
      out[i + j] = ((X[i] - origin[0]) * Rw[3 * j] + (X[i + 1] - origin[1]) * Rw[3 * j + 1] + (X[i + 2] - origin[2]) * Rw[3 * j + 2]) * scale;
    return out;
  };
  const sigma = floorSigmaRel(findFloor, raw, cams, upHint); // on the raw cloud, before scaling
  const pts = toMetric(raw), camsM = toMetric(cams);
  const camHeight = cameraHeightConsistency(Array.from({ length: n }, (_, i) => camsM[3 * i + 1]));
  const roomH = floor.ceilingHeightRaw ? floor.ceilingHeightRaw * scale : null;
  const yaw = dominantYaw(pts, roomH);
  const rotate = (A: Float32Array) => {
    const xz = new Float64Array((A.length / 3) * 2);
    for (let i = 0; i < A.length / 3; i++) { xz[2 * i] = A[3 * i]; xz[2 * i + 1] = A[3 * i + 2]; }
    const r = yawAlign(xz, -yaw);
    for (let i = 0; i < A.length / 3; i++) { A[3 * i] = r[2 * i]; A[3 * i + 2] = r[2 * i + 1]; }
  };
  rotate(pts); rotate(camsM);

  // stage 6: room, ranges, confidence
  progress(6, 0, 1);
  let room: Room = analyze(pts, roomH);
  if (!room || !Object.keys(room).length) room = { incomplete: true, reason: "Too few wall points to measure the room." };
  const unc = estimate(pts, roomH, method, sigma);
  const half = areaHalfWidthRel(unc.ranges);
  const conf = confidence(method, payload.frames.length / Math.max(1, payload.frames_total), room, half, camHeight.inconsistent);
  const scene = {
    video: opts.videoLabel ?? "video",
    scale_method: method,
    frames_extracted: payload.frames_total,
    frames_registered: payload.frames.length,
    frames_with_depth: fits.length,
    sfm_reprojection_error_px: roundTo(payload.reprojection_error_px, 3),
    mean_depth_fit_inliers: roundTo(fits.reduce((s, v) => s + v, 0) / Math.max(1, fits.length), 3),
    points: pts.length / 3,
    cameras: Array.from({ length: n }, (_, i) => [0, 1, 2].map((j) => roundTo(camsM[3 * i + j], 3))),
    room, palette: palette(pts, fused.colors, room, roomH),
    seconds: roundTo((Date.now() - t0) / 1000 + (opts.secondsSoFar ?? 0), 1),
    camera_height: camHeight, uncertainty: unc, confidence: conf, warnings: [] as string[],
  };
  scene.warnings = qualityWarnings({ ...scene, room, camera_height: camHeight });
  raw = new Float32Array(0);
  return { points: pts, colors: fused.colors, views: fused.views, scene };
}

/** The range line the CLI prints, e.g. "3.81 to 4.24 m x 4.74 to 5.26 m, area 18 to 22.3 m²". */
export function rangeLine(scene: { uncertainty: { ranges: Record<string, [number, number | null]> | null } }): string | null {
  const r = scene.uncertainty.ranges;
  return r ? `${formatRange(r.length_m, "m")} x ${formatRange(r.width_m, "m")}, area ${formatRange(r.area_m2, "m²")}` : null;
}

/** Binary little-endian PLY, byte for byte what pipeline.write_ply writes (x y z float32, red green blue uchar, views uchar). */
export function writePly(points: Float32Array, colors: Uint8Array, views: Uint8Array): Uint8Array {
  const n = points.length / 3, head = new TextEncoder().encode(
    `ply\nformat binary_little_endian 1.0\nelement vertex ${n}\nproperty float x\nproperty float y\nproperty float z\n` +
    "property uchar red\nproperty uchar green\nproperty uchar blue\nproperty uchar views\nend_header\n");
  const out = new Uint8Array(head.length + n * 16), dv = new DataView(out.buffer);
  out.set(head);
  for (let i = 0; i < n; i++) {
    const o = head.length + i * 16;
    for (let j = 0; j < 3; j++) dv.setFloat32(o + 4 * j, points[3 * i + j], true);
    out[o + 12] = colors[3 * i]; out[o + 13] = colors[3 * i + 1]; out[o + 14] = colors[3 * i + 2]; out[o + 15] = views[i];
  }
  return out;
}
