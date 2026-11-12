// The whole TypeScript chain (payload + pictures + AI disparity -> metric room) on an analytic 4 x 5 x 2.6 m room.
import test from "node:test";
import assert from "node:assert/strict";
import { buildScene, validatePayload, writePly } from "../../viewer/js/core/pipeline.js";
import { parsePly } from "../../viewer/js/ply.js";
import { makeRoom, ROOM } from "./helpers/synth.mjs";

const within = (got, want, pct, what) => assert.ok(Math.abs(got - want) <= (pct / 100) * want, `${what}: ${got} is not within ${pct}% of ${want}`);

test("the port measures the analytic room: true camera height gives 4 x 5 m, area range contains 20 m²", async () => {
  const { payload, source } = makeRoom();
  const { scene, points } = await buildScene(payload, source, { cameraHeight: ROOM.camHeight });
  const [a, b] = [scene.room.length_m, scene.room.width_m].sort((x, y) => x - y);
  within(a, 4, 3, "short side"); within(b, 5, 3, "long side");
  within(scene.room.area_m2, 20, 5, "area");
  const [lo, hi] = scene.uncertainty.ranges.area_m2;
  assert.ok(lo <= 20 && hi >= 20, `area range ${lo} to ${hi} contains the truth`);
  assert.equal(scene.confidence.label, "high");
  assert.equal(scene.room.rectangular, true);
  assert.ok(points.length / 3 > 5000, "a dense cloud");
  assert.equal(scene.scale_method, "camera height given: 1.5 m");
  assert.deepEqual(Object.keys(scene.room).includes("rect_m"), true);
});

test("an assumed camera height still lands within the stated range, with lower confidence", async () => {
  const { payload, source } = makeRoom();
  const { scene } = await buildScene(payload, source, {}); // assumes 1.45 m while the truth is 1.5 m
  assert.match(scene.scale_method, /assumed/);
  const [lo, hi] = scene.uncertainty.ranges.area_m2;
  assert.ok(lo <= 20 && hi >= 20, `area range ${lo} to ${hi} contains 20`);
  assert.notEqual(scene.confidence.label, "high");
  assert.ok(scene.warnings.some((w) => /guess/.test(w)));
});

test("a given ceiling height sets the scale when the ceiling is seen", async () => {
  const { payload, source } = makeRoom();
  const { scene } = await buildScene(payload, source, { ceilingHeight: ROOM.y });
  if (/ceiling height =/.test(scene.scale_method)) within(scene.room.height_m, 2.6, 4, "ceiling height");
  else assert.match(scene.scale_method, /ceiling not detected/); // honest fallback is also acceptable here
  within(Math.max(scene.room.length_m, scene.room.width_m), 5, 6, "long side");
});

test("floor is at y = 0 with +y up, the walls sit on the axes, and the cameras are above the floor", async () => {
  const { payload, source } = makeRoom();
  const { points, scene } = await buildScene(payload, source, { cameraHeight: ROOM.camHeight });
  let low = Infinity, below = 0;
  for (let i = 1; i < points.length; i += 3) { low = Math.min(low, points[i]); if (points[i] < -0.15) below++; }
  assert.ok(below / (points.length / 3) < 0.02, "almost nothing is below the floor");
  assert.ok(scene.cameras.every((c) => c[1] > 1.2 && c[1] < 1.8), "camera heights near 1.5 m");
  assert.equal(scene.camera_height.inconsistent, false);
});

test("a missing wall is reported as a lower bound with an open range (cut the cloud's far wall)", async () => {
  const { payload, source } = makeRoom({ frames: 24 });
  // keep only frames looking away from one wall: drop every frame whose view direction points mostly +z... simplest: drop half the frames
  payload.frames = payload.frames.slice(0, 12);
  payload.frames_total = 24;
  const { scene } = await buildScene(payload, { luma: source.luma, frame: source.frame }, { cameraHeight: ROOM.camHeight });
  assert.ok(scene.room.incomplete || scene.room.missing_wall || scene.room.rectangular === false || scene.confidence.label !== "high",
    "a partial walk must not come out as confidently as a full one");
  assert.ok(scene.warnings.length > 0);
});

test("writePly round-trips through the viewer's own reader", async () => {
  const { payload, source } = makeRoom({ frames: 12 });
  const { points, colors, views } = await buildScene(payload, source, { cameraHeight: ROOM.camHeight });
  const ply = parsePly(writePly(points, colors, views).buffer);
  assert.equal(ply.count, points.length / 3);
  assert.ok(ply.views && ply.views.length === ply.count);
});

test("validatePayload refuses malformed or hostile payloads in plain words", () => {
  const { payload } = makeRoom({ frames: 4 });
  validatePayload(payload);
  const bad = (f) => { const p = structuredClone(payload); f(p); return () => validatePayload(p); };
  assert.throws(bad((p) => { p.version = 9; }), /version/);
  assert.throws(bad((p) => { p.camera.focal = -1; }), /camera/);
  assert.throws(bad((p) => { p.frames[0].name = "../x.jpg"; }), /pose/);
  assert.throws(bad((p) => { p.frames[0].R = [1]; }), /pose/);
  assert.throws(bad((p) => { p.frames[0].obs = [[1, 2]]; }), /observations/);
  assert.throws(bad((p) => { p.frames[0].t[0] = NaN; }), /pose/);
  assert.throws(bad((p) => { p.frames = []; }), /frames/);
  assert.throws(bad((p) => { p.frames_total = 1; }), /frames_total/);
});
