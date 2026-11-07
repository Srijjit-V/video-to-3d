// Ways to colour the point cloud: true colour, height, distance from the camera path, frames that saw the point.

export const RAMP = ["#5b8cff", "#2dd4bf", "#fde047", "#fb923c", "#fb7185"];  // cool -> warm, from DESIGN.md

const RAMP_RGB = RAMP.map((h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]);

/** t in 0..1 -> [r,g,b] 0..255 along the ramp. */
export function rampColor(t) {
  const x = Math.min(1, Math.max(0, t)) * (RAMP_RGB.length - 1), i = Math.min(RAMP_RGB.length - 2, Math.floor(x)), f = x - i;
  return RAMP_RGB[i].map((v, k) => v + (RAMP_RGB[i + 1][k] - v) * f);
}

/** Value at fraction q (0..1) of the sorted values; samples big arrays so it stays fast. */
export function percentile(values, q, max = 20000) {
  const step = Math.max(1, Math.floor(values.length / max)), s = [];
  for (let i = 0; i < values.length; i += step) s.push(values[i]);
  s.sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * (s.length - 1)))];
}

/** Which colour modes this scene can show, and why not. */
export function availableModes(data, meta) {
  const hasCams = Array.isArray(meta?.cameras) && meta.cameras.length > 0;
  return [
    { id: "true", label: "True colour", ok: true },
    { id: "height", label: "Height above floor", ok: true },
    { id: "distance", label: "Distance from camera path", ok: hasCams, why: "This scene has no camera path." },
    { id: "views", label: "Frames that saw the point", ok: !!data.views, why: "This cloud has no view counts (it was made by an older version)." },
  ];
}

/**
 * Colours for `mode`: { colors: Float32Array (0..1), legend } where legend is
 * { title, lo, hi, unit } for the ramp modes and null for true colour. Normalised to the 2nd-98th percentile.
 */
export function colorize(mode, data, meta) {
  const n = data.count, out = new Float32Array(n * 3);
  if (mode === "true") {
    for (let i = 0; i < n * 3; i++) out[i] = data.colors[i] / 255;
    return { colors: out, legend: null };
  }
  let values, title, unit;
  if (mode === "height") {
    values = new Float32Array(n);
    for (let i = 0; i < n; i++) values[i] = data.positions[3 * i + 1];
    title = "Height above floor"; unit = "m";
  } else if (mode === "distance") {
    const cams = meta.cameras;
    values = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const x = data.positions[3 * i], y = data.positions[3 * i + 1], z = data.positions[3 * i + 2];
      let best = Infinity;
      for (let c = 0; c < cams.length; c++) {
        const dx = x - cams[c][0], dy = y - cams[c][1], dz = z - cams[c][2], d = dx * dx + dy * dy + dz * dz;
        if (d < best) best = d;
      }
      values[i] = Math.sqrt(best);
    }
    title = "Distance from camera path"; unit = "m";
  } else if (mode === "views") {
    values = Float32Array.from(data.views);
    title = "Frames that saw the point"; unit = "";
  } else throw new Error(`Unknown colour mode: ${mode}`);
  const lo = percentile(values, 0.02), hi = Math.max(percentile(values, 0.98), lo + 1e-6);
  for (let i = 0; i < n; i++) {
    const [r, g, b] = rampColor((values[i] - lo) / (hi - lo));
    out[3 * i] = r / 255; out[3 * i + 1] = g / 255; out[3 * i + 2] = b / 255;
  }
  return { colors: out, legend: { title, lo, hi, unit } };
}
