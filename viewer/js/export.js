// Floor-plan export (SVG + JSON), built from scene.json in the browser. Nothing is sent anywhere.
// scene.json is untrusted, so only validated numbers are used; text such as the video name is never exported.
import { fmtRange } from "./format.js";

const fin = (v) => typeof v === "number" && Number.isFinite(v);
const rng = (r, k) => (Array.isArray(r) && fin(r[0]) && (r[1] == null || fin(r[1])) ? [r[0] * k, r[1] == null ? null : r[1] * k] : null);

/** Floor plan as plain data (metres). `k` is the user's calibration factor; returns null if there is no room box. */
export function floorPlanJson(scene, k = 1) {
  const room = scene?.room, rect = room?.rect_m;
  if (!fin(k) || k <= 0 || !Array.isArray(rect) || rect.length !== 4 || !rect.every(fin)) return null;
  const sq = k * k, ranges = scene.uncertainty?.ranges || {};
  const cams = (Array.isArray(scene.cameras) ? scene.cameras : [])
    .filter((c) => Array.isArray(c) && fin(c[0]) && fin(c[2])).map((c) => [c[0] * k, c[2] * k]);
  const out = {
    unit: "m",
    note: "Estimate from a phone video. Top-down view: x is left-right, z is front-back; the floor is y = 0.",
    room: {
      rect_m: rect.map((v) => v * k),
      length_m: fin(room.length_m) ? room.length_m * k : null,
      width_m: fin(room.width_m) ? room.width_m * k : null,
      area_m2: fin(room.area_m2) ? room.area_m2 * sq : null,
      height_m: fin(room.height_m) ? room.height_m * k : null,
      rectangular: room.rectangular === true,
      missing_wall: room.missing_wall === true,
    },
    ranges: {
      length_m: rng(ranges.length_m, k), width_m: rng(ranges.width_m, k), area_m2: rng(ranges.area_m2, sq),
    },
    confidence: scene.confidence && fin(scene.confidence.score)
      ? { score: scene.confidence.score, label: ["high", "medium", "low"].includes(scene.confidence.label) ? scene.confidence.label : null }
      : null,
    camera_path_m: cams,
  };
  return out;
}

/** Floor plan as a standalone SVG string (about 640 px wide, 1 m grid, room box, camera path, dimensions). */
export function floorPlanSvg(scene, k = 1) {
  const j = floorPlanJson(scene, k);
  if (!j) return null;
  const [x0, z0, x1, z1] = j.room.rect_m, pad = 0.9, px = 100;
  const xs = [x0, x1, ...j.camera_path_m.map((c) => c[0])], zs = [z0, z1, ...j.camera_path_m.map((c) => c[1])];
  const lo = [Math.min(...xs) - pad, Math.min(...zs) - pad], hi = [Math.max(...xs) + pad, Math.max(...zs) + pad];
  const W = Math.round((hi[0] - lo[0]) * px), H = Math.round((hi[1] - lo[1]) * px) + 40;
  const X = (x) => +((x - lo[0]) * px).toFixed(1), Z = (z) => +((z - lo[1]) * px).toFixed(1);
  const grid = [];
  for (let g = Math.ceil(lo[0]); g < hi[0]; g++) grid.push(`<line x1="${X(g)}" y1="0" x2="${X(g)}" y2="${H - 40}"/>`);
  for (let g = Math.ceil(lo[1]); g < hi[1]; g++) grid.push(`<line x1="0" y1="${Z(g)}" x2="${W}" y2="${Z(g)}"/>`);
  const path = j.camera_path_m.map((c) => `${X(c[0])},${Z(c[1])}`).join(" ");
  const r = j.ranges, one = (v) => (fin(v) ? v.toFixed(1) : "–");
  const areaTxt = r.area_m2 ? `Area ${fmtRange(r.area_m2, 1, "m²")}` : `Area ${one(j.room.area_m2)} m²`;
  const conf = j.confidence?.label ? `, confidence ${j.confidence.label}` : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="system-ui, sans-serif">
<title>Floor plan (estimate)</title>
<rect width="${W}" height="${H}" fill="#ffffff"/>
<g stroke="#d7dbe2" stroke-width="1">${grid.join("")}</g>
<rect x="${X(x0)}" y="${Z(z0)}" width="${X(x1) - X(x0)}" height="${Z(z1) - Z(z0)}" fill="#e8f5ec" stroke="#1f7a43" stroke-width="3"/>
${path ? `<polyline points="${path}" fill="none" stroke="#d9730d" stroke-width="2"/>` : ""}
<text x="${X((x0 + x1) / 2)}" y="${Z(z0) - 10}" text-anchor="middle" font-size="16" fill="#1f7a43">${one(j.room.length_m)} m</text>
<text x="${X(x1) + 10}" y="${Z((z0 + z1) / 2)}" font-size="16" fill="#1f7a43">${one(j.room.width_m)} m</text>
<line x1="12" y1="${H - 30}" x2="${12 + px}" y2="${H - 30}" stroke="#333" stroke-width="2"/>
<text x="12" y="${H - 12}" font-size="12" fill="#333">1 m</text>
<text x="${W - 12}" y="${H - 12}" text-anchor="end" font-size="12" fill="#333">${areaTxt}${conf} (estimate)</text>
</svg>
`;
}
