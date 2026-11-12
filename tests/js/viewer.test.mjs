import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parsePly } from "../../viewer/js/ply.js";
import { colorize, availableModes, rampColor, percentile } from "../../viewer/js/colors.js";
import { demoSteps } from "../../viewer/js/demo.js";
import { fmtLen, toHex, fromHex, mmss, esc, textOn, fmtRange, confidenceView } from "../../viewer/js/format.js";

function makePly(rows, withViews = true) {
  const head = `ply\nformat binary_little_endian 1.0\nelement vertex ${rows.length}\nproperty float x\nproperty float y\nproperty float z\n` +
    `property uchar red\nproperty uchar green\nproperty uchar blue\n${withViews ? "property uchar views\n" : ""}end_header\n`;
  const stride = withViews ? 16 : 15, buf = new ArrayBuffer(head.length + rows.length * stride);
  new Uint8Array(buf).set(new TextEncoder().encode(head));
  const dv = new DataView(buf, head.length);
  rows.forEach((r, i) => {
    r.slice(0, 3).forEach((v, k) => dv.setFloat32(i * stride + 4 * k, v, true));
    r.slice(3, 6).forEach((v, k) => dv.setUint8(i * stride + 12 + k, v));
    if (withViews) dv.setUint8(i * stride + 15, r[6]);
  });
  return buf;
}

test("parsePly reads positions, colours and the views property", () => {
  const d = parsePly(makePly([[1, 2, 3, 10, 20, 30, 4], [-1, 0.5, 9, 255, 0, 128, 7]]));
  assert.equal(d.count, 2);
  assert.deepEqual([...d.positions], [1, 2, 3, -1, 0.5, 9]);
  assert.deepEqual([...d.colors], [10, 20, 30, 255, 0, 128]);
  assert.deepEqual([...d.views], [4, 7]);
});

test("parsePly works without views and says why a bad file fails", () => {
  assert.equal(parsePly(makePly([[0, 0, 0, 1, 2, 3]], false)).views, null);
  assert.throws(() => parsePly(new TextEncoder().encode("hello world").buffer), /doesn't look like a .ply/);
  assert.throws(() => parsePly(new TextEncoder().encode("ply\nformat ascii 1.0\nend_header\n").buffer), /binary/);
  const cut = makePly([[0, 0, 0, 1, 2, 3, 1], [0, 0, 0, 1, 2, 3, 1]]);
  assert.throws(() => parsePly(cut.slice(0, cut.byteLength - 5)), /cut off/);
});

test("parsePly reads the real sample cloud", () => {
  const buf = readFileSync(new URL("../../viewer/sample/cloud.ply", import.meta.url));
  const d = parsePly(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
  assert.ok(d.count > 1000 && d.views && d.views.every((v) => v >= 2));
  const meta = JSON.parse(readFileSync(new URL("../../viewer/sample/scene.json", import.meta.url)));
  assert.equal(meta.points, d.count);
});

const data = { count: 3, positions: new Float32Array([0, 0, 0, 0, 1, 0, 0, 2, 0]), colors: new Uint8Array([255, 0, 0, 0, 255, 0, 0, 0, 255]), views: new Uint8Array([2, 4, 6]) };
const meta = { cameras: [[0, 0, 0]] };

test("true colour is the video's colour, unchanged", () => {
  const { colors, legend } = colorize("true", data, meta);
  assert.deepEqual([...colors].map((v) => Math.round(v * 255)), [...data.colors]);
  assert.equal(legend, null);
});

test("height, distance and views map low to cool and high to warm", () => {
  for (const mode of ["height", "distance", "views"]) {
    const { colors, legend } = colorize(mode, data, meta);
    assert.ok(legend.hi > legend.lo, mode);
    assert.ok(colors[2] > colors[8] - 0.01 || colors[0] < colors[6], `${mode}: ends differ`);
    assert.notDeepEqual([...colors.slice(0, 3)], [...colors.slice(6, 9)], mode);
  }
});

test("modes that can't work are marked unavailable with a reason", () => {
  const modes = Object.fromEntries(availableModes({ views: null }, { cameras: [] }).map((m) => [m.id, m]));
  assert.equal(modes.true.ok, true);
  assert.equal(modes.distance.ok, false);
  assert.equal(modes.views.ok, false);
  assert.match(modes.views.why, /older version/);
});

test("ramp ends and percentile", () => {
  assert.deepEqual(rampColor(0).map(Math.round), [91, 140, 255]);
  assert.deepEqual(rampColor(1).map(Math.round), [251, 113, 133]);
  assert.equal(percentile([5, 1, 3, 2, 4], 0.5), 3);
});

test("formatting helpers", () => {
  assert.equal(fmtLen(3.9), "3.90 m · 12′10″");
  assert.equal(fmtLen(2, 1.5), "3.00 m · 9′10″");
  assert.equal(fmtLen(0.3047), "0.30 m · 1′0″");
  assert.equal(toHex(240, 225, 190), "#f0e1be");
  assert.deepEqual(fromHex("#f0e1be"), [240, 225, 190]);
  assert.equal(fromHex("nope"), null);
  assert.equal(mmss(125), "2:05");
  assert.equal(esc('<img src=x onerror="a">'), "&lt;img src=x onerror=&quot;a&quot;&gt;");
  assert.equal(textOn("#ffffff"), "#07090d");
  assert.equal(textOn("#101010"), "#f4f6fa");
});

test("fmtRange shows two-sided and open-ended ranges, scaled by calibration", () => {
  assert.equal(fmtRange([3.8, 4.2], 1, "m"), "3.8 to 4.2 m");
  assert.equal(fmtRange([2.7, null], 1, "m"), "at least 2.7 m");
  assert.equal(fmtRange([10, 20], 4, "m²"), "40 to 80 m²");
  assert.equal(fmtRange(null, 1, "m"), "–");
});

test("confidenceView gives a label, a score and escapes nothing it does not need to", () => {
  const v = confidenceView({ score: 70, label: "medium", summary: "Good for planning.", reasons: ["a", "b"] });
  assert.deepEqual([v.label, v.text, v.reasons.length], ["medium", "Confidence: medium (70/100)", 2]);
  assert.equal(confidenceView(null), null);
  assert.equal(confidenceView({ score: "x", label: "bogus" }), null);
});

test("demoSteps takes expected values from the scene's own truth, and is null for ordinary scenes", () => {
  const truth = { length_m: 5, width_m: 4, area_m2: 20, door: { height_m: 2.03 } };
  const good = demoSteps({ demo: { kind: "good", truth }, room: { length_m: 4.05, width_m: 5 },
    uncertainty: { ranges: { area_m2: [18.1, 22.2] } }, palette: { walls: [{ hex: "#8f618d" }, { hex: "<b>x</b>" }] } });
  assert.equal(good.length, 6);
  assert.match(good[0].expect, /really 5\.0 × 4\.0 m/);
  assert.match(good[1].expect, /2\.03/);
  assert.match(good[4].expect, /#8f618d/);
  assert.doesNotMatch(good[4].expect, /<b>/); // untrusted palette values are filtered to real hex colours
  const bad = demoSteps({ demo: { kind: "bad", truth }, uncertainty: { ranges: { width_m: [2.57, null] } } });
  assert.equal(bad.length, 3);
  assert.match(bad[1].expect, /at least 2\.57 m/);
  assert.equal(demoSteps({ room: {} }), null);
});

// ---------- floor plan export ----------
import { floorPlanJson, floorPlanSvg } from "../../viewer/js/export.js";

const planScene = {
  room: { rect_m: [-2, -2.5, 2, 2.5], length_m: 4, width_m: 5, area_m2: 20, height_m: 2.4 },
  cameras: [[0, 1.5, -1], [1, 1.5, 0], [0, 1.5, 1]],
  uncertainty: { ranges: { length_m: [3.8, 4.2], width_m: [4.7, 5.3], area_m2: [18, 22] } },
  confidence: { label: "high", score: 90 },
  video: "<script>alert(1)</script>.mp4",
};

test("floor plan JSON holds the room box, ranges, confidence and camera path", () => {
  const j = floorPlanJson(planScene);
  assert.deepEqual(j.room.rect_m, [-2, -2.5, 2, 2.5]);
  assert.deepEqual(j.ranges.area_m2, [18, 22]);
  assert.equal(j.confidence.label, "high");
  assert.deepEqual(j.camera_path_m, [[0, -1], [1, 0], [0, 1]]);
  assert.equal(j.unit, "m");
  assert.equal("video" in j, false); // the file name is not exported
});

test("calibration scales lengths, areas and ranges", () => {
  const j = floorPlanJson(planScene, 1.1);
  assert.equal(+j.room.length_m.toFixed(2), 4.4);
  assert.equal(+j.room.area_m2.toFixed(1), 24.2);
  assert.deepEqual(j.ranges.length_m.map((v) => +v.toFixed(2)), [4.18, 4.62]);
  assert.equal(+j.room.rect_m[2].toFixed(2), 2.2);
});

test("floor plan SVG is well formed, scaled, and carries only numbers from the scene", () => {
  const s = floorPlanSvg(planScene);
  assert.match(s, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
  assert.match(s, /<rect /);
  assert.match(s, /4\.0 m/);
  assert.match(s, /5\.0 m/);
  assert.ok(!s.includes("<script"));
  assert.ok(!s.includes("alert"));
  assert.match(s, /<polyline /);
});

test("an open-ended range stays open in the export", () => {
  const sc = { ...planScene, uncertainty: { ranges: { length_m: [2.7, null], width_m: [4.7, 5.3], area_m2: [9.8, null] } } };
  assert.deepEqual(floorPlanJson(sc).ranges.area_m2, [9.8, null]);
  assert.match(floorPlanSvg(sc), /at least 9\.8/);
});

test("no room box, or non-finite numbers, means no export", () => {
  assert.equal(floorPlanJson({ room: { incomplete: true } }), null);
  assert.equal(floorPlanSvg({ room: { rect_m: [0, 0, NaN, 1] } }), null);
  assert.equal(floorPlanJson(planScene, 0), null);
});

// ---------- browser frame picking and zip ----------
import { checkVideo, laplacianVariance, candidateTimes, pickSharpest, fitSide } from "../../viewer/js/frames.js";
import { makeZip, crc32 } from "../../viewer/js/zip.js";

test("checkVideo refuses too short, too long, too big and huge videos in plain words", () => {
  const ok = { duration: 20, width: 1920, height: 1080, size: 50e6 };
  assert.equal(checkVideo(ok), null);
  assert.match(checkVideo({ ...ok, duration: 1 }), /only 1\.0 seconds/);
  assert.match(checkVideo({ ...ok, duration: 301 }), /longer than 300/);
  assert.match(checkVideo({ ...ok, size: 2.2e9 }), /bigger than 2 GB/);
  assert.match(checkVideo({ ...ok, width: 7680, height: 4320 }), /larger than 4K/);
  assert.match(checkVideo({ ...ok, duration: NaN }), /couldn't read/);
  assert.match(checkVideo({ ...ok, width: 0 }), /couldn't read/);
});

test("laplacianVariance is high for detail, zero for flat, and ignores colour order", () => {
  const w = 16, h = 16, flat = new Uint8ClampedArray(w * h * 4).fill(120);
  const noisy = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) { const v = (i * 97) % 255; noisy.set([v, v, v, 255], i * 4); }
  assert.equal(laplacianVariance(flat, w, h), 0);
  assert.ok(laplacianVariance(noisy, w, h) > 1000);
  const soft = new Uint8ClampedArray(w * h * 4);   // a gentle ramp: little curvature
  for (let i = 0; i < w * h; i++) { const v = (i % w) * 8; soft.set([v, v, v, 255], i * 4); }
  assert.ok(laplacianVariance(soft, w, h) < laplacianVariance(noisy, w, h) / 100);
});

test("candidateTimes spreads windows over the video and stays inside it", () => {
  const w = candidateTimes(30, 10, 3);
  assert.equal(w.length, 10);
  assert.ok(w.every((c) => c.length === 3 && c.every((t) => t > 0 && t < 30)));
  assert.ok(w[0][0] < w[1][0] && w[8][2] < w[9][2]);
  assert.equal(candidateTimes(2, 80, 3).length, 80); // short video: still the requested windows, closely spaced
});

test("pickSharpest takes the best candidate of each window", () => {
  assert.deepEqual(pickSharpest([[1, 5, 2], [9, 3, 3], [0, 0, 4]]), [1, 0, 2]);
  assert.deepEqual(pickSharpest([[NaN, 2]]), [1]);
});

test("fitSide keeps aspect ratio and never upscales", () => {
  assert.deepEqual(fitSide(1920, 1080, 1024), [1024, 576]);
  assert.deepEqual(fitSide(1080, 1920, 1024), [576, 1024]);
  assert.deepEqual(fitSide(640, 480, 1024), [640, 480]);
});

test("crc32 matches the standard check value", () => {
  assert.equal(crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
});

test("makeZip writes a stored zip that a real unzip can read", async () => {
  const { execFileSync } = await import("node:child_process");
  const { writeFileSync, mkdtempSync, readFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const files = [{ name: "frame_0000.jpg", bytes: new Uint8Array([1, 2, 3, 4, 5]) }, { name: "frame_0001.jpg", bytes: new Uint8Array(70000).fill(7) }];
  const z = makeZip(files);
  const dir = mkdtempSync(join(tmpdir(), "zip-"));
  writeFileSync(join(dir, "a.zip"), z);
  execFileSync("unzip", ["-o", "-q", join(dir, "a.zip"), "-d", join(dir, "out")]);
  assert.deepEqual([...readFileSync(join(dir, "out", "frame_0000.jpg"))], [1, 2, 3, 4, 5]);
  assert.equal(readFileSync(join(dir, "out", "frame_0001.jpg")).length, 70000);
  assert.throws(() => makeZip([{ name: "../x.jpg", bytes: new Uint8Array(1) }]), /name/);
});

// ---------- hybrid helpers that need no browser ----------
test("parseServerUrl accepts http(s) origins and refuses everything else", async () => {
  const { parseServerUrl, cameraCentres, DEFAULT_SERVER } = await import("../../viewer/js/hybrid.js");
  assert.equal(parseServerUrl("http://127.0.0.1:8787/"), "http://127.0.0.1:8787");
  assert.equal(parseServerUrl("https://sfm.example.com/v1/x?y=1"), "https://sfm.example.com");
  assert.equal(parseServerUrl(""), DEFAULT_SERVER);
  for (const bad of ["ftp://x", "javascript:alert(1)", "file:///etc/passwd", "not a url", "https://user:pw@x.com"]) assert.throws(() => parseServerUrl(bad));
  // identity pose at t = (1, 2, 3): the camera sits at (-1, -2, -3)
  const p = { frames: [{ R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [1, 2, 3] }, { R: [1, 2], t: [0, 0, 0] }] };
  assert.deepEqual(cameraCentres(p), [[-1, -2, -3]]);
});
