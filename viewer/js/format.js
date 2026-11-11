// Small pure helpers: escaping, lengths, colours, time.

/** scene.json is data, not markup: escape anything from it before it goes into innerHTML. */
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** 3.9 -> "3.90 m · 12′10″" (cal is the user's scale correction). */
export function fmtLen(m, cal = 1) {
  m *= cal;
  const inches = m / 0.0254, ft = Math.floor(inches / 12);
  let inch = Math.round(inches - ft * 12);
  return inch === 12 ? `${m.toFixed(2)} m · ${ft + 1}′0″` : `${m.toFixed(2)} m · ${ft}′${inch}″`;
}

export const toHex = (r, g, b) => "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

export function fromHex(h) {
  const m = /^#?([0-9a-f]{6})$/i.exec(h);
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}

/** Seconds -> "m:ss". */
export const mmss = (sec) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;

/** Readable text colour (dark or light) for a background hex. */
export function textOn(hex) {
  const [r, g, b] = fromHex(hex) || [0, 0, 0];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140 ? "#07090d" : "#f4f6fa";
}

/** [lo, hi] -> "3.8 to 4.2 m"; [lo, null] -> "at least 2.7 m". `k` rescales (calibration, or k*k for areas). */
export function fmtRange(r, k = 1, unit = "m", digits = 1) {
  if (!Array.isArray(r) || !Number.isFinite(r[0])) return "–";
  const f = (v) => String(+(v * k).toFixed(digits));
  return r[1] == null ? `at least ${f(r[0])} ${unit}` : `${f(r[0])} to ${f(r[1])} ${unit}`;
}

/** scene.json "confidence" -> what the panel shows, or null if it is missing or malformed (it is untrusted data). */
export function confidenceView(c) {
  if (!c || !["high", "medium", "low"].includes(c.label) || !Number.isFinite(c.score)) return null;
  return {
    label: c.label,
    text: `Confidence: ${c.label} (${Math.round(c.score)}/100)`,
    summary: String(c.summary || ""),
    reasons: (Array.isArray(c.reasons) ? c.reasons : []).map(String),
  };
}
