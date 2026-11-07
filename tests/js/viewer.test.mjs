import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parsePly } from "../../viewer/js/ply.js";
import { colorize, availableModes, rampColor, percentile } from "../../viewer/js/colors.js";
import { fmtLen, toHex, fromHex, mmss, esc, textOn } from "../../viewer/js/format.js";

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
