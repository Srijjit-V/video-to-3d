// Pure helpers for picking sharp frames from a video in the browser (mirrors src/vid3d/frames.py).

export const LIMITS = { minSeconds: 3, maxSeconds: 300, maxBytes: 2 * 1024 ** 3, maxPixels: 3840 * 2160 };

/** Plain-language reason a video can't be used, or null. Checked from metadata, before any frame is decoded. */
export function checkVideo({ duration, width, height, size }) {
  if (![duration, width, height].every((v) => Number.isFinite(v)) || width <= 0 || height <= 0)
    return "This browser couldn't read that video. Try an .mp4 (H.264) file, or use Chrome.";
  if (size > LIMITS.maxBytes) return "That video is bigger than 2 GB. Trim it or lower its resolution.";
  if (duration < LIMITS.minSeconds) return `The video is only ${duration.toFixed(1)} seconds long. Film at least ${LIMITS.minSeconds} seconds (10 to 30 is best).`;
  if (duration > LIMITS.maxSeconds) return `That video is longer than ${LIMITS.maxSeconds} seconds. Trim it to the walk around the room (10 to 30 seconds is plenty).`;
  if (width * height > LIMITS.maxPixels) return "That video is larger than 4K. Export it at a lower resolution.";
  return null;
}

/** Variance of the Laplacian of the grey image (RGBA input): high = sharp, low = blurry. Same measure as frames.py. */
export function laplacianVariance(rgba, w, h) {
  const g = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) g[i] = 0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2];
  let sum = 0, sum2 = 0, n = 0;
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x, l = g[i - 1] + g[i + 1] + g[i - w] + g[i + w] - 4 * g[i];
    sum += l; sum2 += l * l; n++;
  }
  if (!n) return 0;
  const mean = sum / n;
  return Math.max(0, sum2 / n - mean * mean);
}

/** `windows` equal slices of the video, `per` evenly spaced candidate times in each (never at 0 or the very end). */
export function candidateTimes(duration, windows, per) {
  const out = [], span = duration / windows;
  for (let i = 0; i < windows; i++) {
    const row = [];
    for (let j = 0; j < per; j++) row.push(Math.min(duration - 0.05, Math.max(0.05, i * span + ((j + 0.5) / per) * span)));
    out.push(row);
  }
  return out;
}

/** Index of the sharpest candidate in each window (NaN scores lose). */
export function pickSharpest(scores) {
  return scores.map((row) => row.reduce((best, s, j) => (Number.isFinite(s) && (!Number.isFinite(row[best]) || s > row[best]) ? j : best), 0));
}

/** Size that fits `max` pixels on the long side, keeping the aspect ratio, never enlarging. */
export function fitSide(w, h, max) {
  const s = Math.min(1, max / Math.max(w, h));
  return [Math.round(w * s), Math.round(h * s)];
}
