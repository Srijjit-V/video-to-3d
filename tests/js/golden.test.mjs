// The TypeScript port (viewer/js/core) must reproduce the Python reference within stated tolerances.
// Vectors come from scripts/make_golden.py. Deterministic functions: tight tolerance. Anything that draws random
// numbers (RANSAC, Theil-Sen, k-means, bootstrap) uses its own generator, so it must agree statistically, not bit for bit.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { alignDisparity, metricDepth } from "../../viewer/js/core/depth.js";
import { backproject, fuse, findFloor, floorFrame, yawAlign } from "../../viewer/js/core/geometry.js";

const G = JSON.parse(readFileSync(new URL("../golden/golden.json", import.meta.url)));
const flat = (rows) => Float64Array.from(rows.flat());
const near = (a, b, tol, msg = "") => assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${msg} ${a} vs ${b} (tol ${tol})`);

test("alignDisparity recovers the same affine fit as Python (random start, so 1.5% tolerance)", () => {
  const g = G.align, fit = alignDisparity(Float64Array.from(g.disp), Float64Array.from(g.z));
  near(fit.a, g.a, 0.015, "a"); near(fit.b, g.b, 0.015, "b"); near(fit.inliers, g.inliers, 0.05, "inliers");
});

test("alignDisparity refuses too few points or a flat disparity", () => {
  assert.equal(alignDisparity(new Float64Array(10).fill(0.5), new Float64Array(10).fill(2)), null);
  assert.equal(alignDisparity(new Float64Array(100).fill(0.5), new Float64Array(100).fill(2)), null);
});

test("metricDepth matches Python: same NaN pattern (flying pixels removed) and values", () => {
  const g = G.metric, d = metricDepth(Float32Array.from(g.disp.flat()), g.h, g.w, g.a, g.b, g.zmin, g.zmax);
  let mism = 0, vals = 0;
  g.depth.flat().forEach((v, i) => {
    if ((v === null) !== Number.isNaN(d[i])) mism++;
    else if (v !== null) { vals++; near(d[i], v, 1e-5, `depth[${i}]`); }
  });
  assert.ok(vals > 100, "some depth survives");
  assert.ok(mism <= 2, `${mism} pixels differ in validity (float32 rounding at the edge threshold)`);
  assert.ok(g.depth.flat().some((v) => v === null), "the edge was removed in the reference too");
});

test("backproject reproduces Python's points and colours, with lens distortion", () => {
  const g = G.backproject;
  const view = { fx: g.K[0][0], fy: g.K[1][1], cx: g.K[0][2], cy: g.K[1][2], R: flat(g.R), t: g.t };
  const out = backproject(view, Float32Array.from(g.depth.flat().map((v) => (v === null ? NaN : v))), Uint8Array.from(g.rgb.flat(2)), g.h, g.w, g.stride, g.k1);
  assert.equal(out.points.length, g.points.length * 3);
  g.points.forEach((p, i) => p.forEach((v, j) => near(out.points[3 * i + j], v, 2e-5, `p[${i}][${j}]`)));
  assert.deepEqual([...out.colors], g.colors.flat());
});

test("fuse keeps voxels seen by 2+ frames, in numpy.unique order, with the same averages", () => {
  const g = G.fuse, out = fuse(flat(g.points), flat(g.colors), Float64Array.from(g.frames), g.voxel, g.min_views);
  assert.equal(out.points.length / 3, g.out_points.length);
  g.out_points.forEach((p, i) => p.forEach((v, j) => near(out.points[3 * i + j], v, 1e-5)));
  assert.deepEqual([...out.colors], g.out_colors.flat());
  assert.deepEqual([...out.views], g.out_views);
  assert.throws(() => fuse([0, 0, 0, 1, 1, 1], [0, 0, 0, 0, 0, 0], [1, 0], 0.5), /non-decreasing/);
});

test("findFloor and floorFrame agree with Python on a tilted, unscaled copy of the sample room", () => {
  const g = G.floor, floor = findFloor(flat(g.points), flat(g.cams), g.up_hint);
  const angle = (Math.acos(Math.min(1, floor.up.reduce((s, v, i) => s + v * g.up[i], 0))) * 180) / Math.PI;
  assert.ok(angle < 0.5, `floor normal differs by ${angle} degrees`);
  near(floor.camHeightRaw, g.cam_height_raw, 0.02, "camera height");
  assert.equal(floor.ceilingHeightRaw, g.ceiling_height_raw); // the sample has no visible ceiling: both null
  const fr = floorFrame(floor, flat(g.cams));
  near(fr.Rw[4], g.Rw[1][1], 0.01, "new y axis is the floor normal");
});

test("findFloor throws a plain message when there is no floor to find", () => {
  const pts = []; for (let i = 0; i < 300; i++) pts.push(Math.random(), 1 + Math.random() * 0.01, Math.random()); // everything at one height, camera below it
  assert.throws(() => findFloor(pts, [0.5, 0.2, 0.5], [0, 1, 0]), /floor|cameras below/i);
});

test("yawAlign matches Python", () => {
  const g = G.yaw_align, out = yawAlign(flat(g.xz), g.deg);
  g.out.flat().forEach((v, i) => near(out[i], v, 1e-6));
});

import { analyze, dominantYaw, extent, palette, sideSupport, wallPoints, wallSupport } from "../../viewer/js/core/floorplan.js";
import { dominantColors, exposureGains, normalizeFrame } from "../../viewer/js/core/color.js";
import { areaHalfWidthRel, cameraHeightConsistency, confidence, estimate, formatRange, scaleSource } from "../../viewer/js/core/uncertainty.js";

const sameRoom = (a, b) => {
  for (const k of Object.keys(b)) {
    if (Array.isArray(b[k])) b[k].forEach((v, i) => near(a[k][i], v, 1e-6, `${k}[${i}]`));
    else if (typeof b[k] === "number") near(a[k], b[k], 1e-6, k);
    else assert.equal(a[k], b[k], k);
  }
};

test("analyze gives the same room, flags and rounded numbers as Python (box, L-shape)", () => {
  sameRoom(analyze(flat(G.floorplan.points), null), G.floorplan.room);
  const l = analyze(flat(G.floorplan_l.points), null);
  sameRoom(l, G.floorplan_l.room);
  assert.equal(l.rectangular, false);
});

test("extent, sideSupport and wallSupport match Python, including a custom threshold", () => {
  const g = G.floorplan, xz = wallPoints(flat(g.points), null);
  assert.equal(xz.length / 2, g.wall_xz_count);
  const col = (k) => Float64Array.from({ length: xz.length / 2 }, (_, i) => xz[2 * i + k]);
  extent(col(0)).forEach((v, i) => near(v, g.extent_x[i], 2e-6));
  extent(col(1)).forEach((v, i) => near(v, g.extent_z[i], 2e-6));
  extent(col(0), 0.2).forEach((v, i) => near(v, g.extent_x_20[i], 2e-6));
  sideSupport(xz, g.room.rect_m).forEach((v, i) => near(v, g.sides[i], 2e-6));
  near(wallSupport(xz, g.room.rect_m), g.support, 2e-6);
});

test("dominantYaw finds the same wall angle (within 0.2 degrees)", () => {
  near(dominantYaw(flat(G.yaw.points), null), G.yaw.deg, 0.2 / 23, "yaw"); // relative to 23 degrees
  assert.equal(dominantYaw([0, 0, 0], null), 0);
});

test("confidence, camera-height consistency and range formatting match Python exactly", () => {
  for (const c of G.confidence) assert.deepEqual(confidence(c.method, c.share, c.room, c.hw, c.inc), c.out);
  const h = G.height_consistency;
  assert.deepEqual(cameraHeightConsistency(h.heights), h.out);
  assert.equal(formatRange([3.8, 4.2], "m"), "3.8 to 4.2 m");
  assert.equal(formatRange([2.7, null], "m"), "at least 2.7 m");
  assert.equal(areaHalfWidthRel({ area_m2: [18, 22] }), 0.1);
  assert.equal(areaHalfWidthRel({ area_m2: [18, null] }), null);
  assert.equal(scaleSource("camera held at ~1.45 m above floor (assumed)"), "assumed");
  assert.equal(scaleSource("ceiling height = 2.44 m"), "ceiling");
  assert.equal(scaleSource("camera height given: 1.5 m"), "given");
});

test("Monte Carlo ranges agree with Python's (own random generator: ends within 4% of the range width + 0.5%)", () => {
  const g = G.uncertainty, e = estimate(flat(g.points), null, g.method, g.floor_sigma), ref = g.estimate;
  assert.equal(e.scale_source, ref.scale_source);
  near(e.scale_sigma_rel, ref.scale_sigma_rel, 1e-6);
  for (const k of ["length_m", "width_m", "area_m2"]) {
    const [rlo, rhi] = ref.ranges[k], width = rhi - rlo;
    assert.ok(Math.abs(e.ranges[k][0] - rlo) <= 0.04 * width + 0.005 * rlo, `${k} low ${e.ranges[k][0]} vs ${rlo}`);
    assert.ok(Math.abs(e.ranges[k][1] - rhi) <= 0.04 * width + 0.005 * rhi, `${k} high ${e.ranges[k][1]} vs ${rhi}`);
  }
  assert.deepEqual(e.central, ref.central);
});

test("exposure gains and frame normalisation match Python", () => {
  exposureGains(G.exposure.lumas).forEach((v, i) => near(v, G.exposure.gains[i], 2e-6));
  const g = G.normalize, out = normalizeFrame(Uint8Array.from(g.rgb.flat(2)), g.h * g.w, g.gain), ref = g.out.flat(2);
  let worst = 0; out.forEach((v, i) => { worst = Math.max(worst, Math.abs(v - ref[i])); });
  assert.ok(worst <= 1, `largest pixel difference ${worst} (float32 rounding)`);
});

test("dominant colours and the room palette find the same swatches (k-means: shares 3%, colours 8 per channel)", () => {
  const close = (got, ref) => {
    assert.equal(got.length, ref.length);
    got.forEach((s, i) => {
      assert.ok(Math.abs(s.share - ref[i].share) <= 0.03, `share ${s.share} vs ${ref[i].share}`);
      for (const c of [1, 3, 5]) assert.ok(Math.abs(parseInt(s.hex.slice(c, c + 2), 16) - parseInt(ref[i].hex.slice(c, c + 2), 16)) <= 8, `${s.hex} vs ${ref[i].hex}`);
    });
  };
  close(dominantColors(Uint8Array.from(G.dominant.rgb.flat())), G.dominant.out);
  const p = G.palette, got = palette(flat(p.points), Uint8Array.from(p.colors.flat()), p.room, null);
  for (const k of ["floor", "ceiling", "walls"]) close(got[k], p.out[k]);
  assert.deepEqual(dominantColors(new Uint8Array(30)), []); // too few points
});

test("findFloor detects a real ceiling like Python, and the ceiling-to-camera ratio is right (2.6 / 1.5)", () => {
  const g = G.floor_ceiling, f = findFloor(flat(g.points), flat(g.cams), g.up_hint);
  assert.ok(g.ceiling_height_raw, "the reference found the ceiling");
  assert.ok(f.ceilingHeightRaw, "the port found the ceiling");
  near(f.ceilingHeightRaw, g.ceiling_height_raw, 0.02, "ceiling height");
  near(f.camHeightRaw, g.cam_height_raw, 0.02, "camera height");
  near(f.ceilingHeightRaw / f.camHeightRaw, g.true_ratio, 0.04, "ratio to the truth");
});
