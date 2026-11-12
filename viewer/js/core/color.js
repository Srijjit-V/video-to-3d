// Colour handling (port of src/vid3d/color.py): exposure gains, frame normalisation, dominant colours.
import { Rng, median, percentiles } from "./linalg.js";
export const GAIN_LIMITS = [0.75, 1.35];
export const TARGET_LUMA = [90, 150];
const LOW_CONTRAST = 180;
const clip = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export const roundTo = (x, nd) => { const f = 10 ** nd; return Math.round(x * f) / f; };
/** Median brightness of an RGB frame, 0-255 (OpenCV's integer grey conversion). */
export function frameLuma(rgb, n) {
    const g = new Float64Array(n);
    for (let i = 0; i < n; i++)
        g[i] = (rgb[3 * i] * 4899 + rgb[3 * i + 1] * 9617 + rgb[3 * i + 2] * 1868 + 8192) >> 14;
    return median(g);
}
/** One gain per frame so every frame ends up with a similar brightness, gently. */
export function exposureGains(lumas) {
    const target = clip(median(lumas), TARGET_LUMA[0], TARGET_LUMA[1]);
    return lumas.map((l) => clip(target / Math.max(l, 1), GAIN_LIMITS[0], GAIN_LIMITS[1]));
}
/** Apply a gain, then gently stretch contrast when the frame looks washed out. Returns new RGB bytes. */
export function normalizeFrame(rgb, n, gain, stretch = 0.5) {
    const out = new Float32Array(n * 3), gray = new Float32Array(n);
    for (let i = 0; i < n * 3; i++)
        out[i] = Math.fround(rgb[i] * gain);
    for (let i = 0; i < n; i++)
        gray[i] = Math.fround((out[3 * i] + out[3 * i + 1] + out[3 * i + 2]) / 3);
    const [lo, hi] = percentiles(gray, [1, 99]);
    if (hi - lo < LOW_CONTRAST && hi > lo) {
        const k = 255 / (hi - lo);
        for (let i = 0; i < n * 3; i++)
            out[i] = out[i] * (1 - stretch) + (out[i] - lo) * k * stretch;
    }
    const res = new Uint8Array(n * 3);
    for (let i = 0; i < n * 3; i++)
        res[i] = clip(out[i], 0, 255); // Uint8Array truncates, like numpy's astype(uint8)
    return res;
}
/** sRGB 0-255 -> OpenCV-style 8-bit Lab (L scaled to 0-255, a and b offset by 128). */
export function rgbToLab8(r, g, b) {
    const lin = (c) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    const R = lin(r), G = lin(g), B = lin(b);
    const X = (0.412453 * R + 0.35758 * G + 0.180423 * B) / 0.950456, Y = 0.212671 * R + 0.71516 * G + 0.072169 * B, Z = (0.019334 * R + 0.119193 * G + 0.950227 * B) / 1.088754;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    const L = Y > 0.008856 ? 116 * Math.cbrt(Y) - 16 : 903.3 * Y;
    return [clip(Math.round((L * 255) / 100), 0, 255), clip(Math.round(500 * (f(X) - f(Y)) + 128), 0, 255), clip(Math.round(200 * (f(Y) - f(Z)) + 128), 0, 255)];
}
/** Most common colours in a set of RGB points (flat bytes), biggest first. Plain k-means in Lab (k-means++ start, best of 3). */
export function dominantColors(rgb, k = 3, maxPoints = 20000) {
    let n = Math.floor(rgb.length / 3);
    if (n < 30)
        return [];
    let pick = null;
    if (n > maxPoints) {
        pick = new Rng(0).choice(n, maxPoints);
        n = maxPoints;
    }
    const px = (i, c) => rgb[3 * (pick ? pick[i] : i) + c];
    const uniq = new Set();
    for (let i = 0; i < n; i++)
        uniq.add((px(i, 0) << 16) | (px(i, 1) << 8) | px(i, 2));
    k = Math.min(k, uniq.size);
    const lab = new Float64Array(n * 3);
    for (let i = 0; i < n; i++)
        lab.set(rgbToLab8(px(i, 0), px(i, 1), px(i, 2)), 3 * i);
    const rng = new Rng(0), d2 = (i, c, j) => (lab[3 * i] - c[3 * j]) ** 2 + (lab[3 * i + 1] - c[3 * j + 1]) ** 2 + (lab[3 * i + 2] - c[3 * j + 2]) ** 2;
    let best = null;
    for (let attempt = 0; attempt < 3; attempt++) {
        const cen = new Float64Array(k * 3), first = rng.int(n);
        cen.set(lab.subarray(3 * first, 3 * first + 3), 0);
        const dist = new Float64Array(n).fill(Infinity);
        for (let c = 1; c < k; c++) {
            let tot = 0;
            for (let i = 0; i < n; i++) {
                dist[i] = Math.min(dist[i], d2(i, cen, c - 1));
                tot += dist[i];
            }
            let r = rng.next() * tot, pickI = n - 1;
            for (let i = 0; i < n; i++) {
                r -= dist[i];
                if (r <= 0) {
                    pickI = i;
                    break;
                }
            }
            cen.set(lab.subarray(3 * pickI, 3 * pickI + 3), 3 * c);
        }
        const labels = new Int32Array(n);
        for (let it = 0; it < 30; it++) {
            for (let i = 0; i < n; i++) {
                let bj = 0, bd = Infinity;
                for (let j = 0; j < k; j++) {
                    const d = d2(i, cen, j);
                    if (d < bd) {
                        bd = d;
                        bj = j;
                    }
                }
                labels[i] = bj;
            }
            const sum = new Float64Array(k * 3), cnt = new Float64Array(k);
            for (let i = 0; i < n; i++) {
                cnt[labels[i]]++;
                for (let c = 0; c < 3; c++)
                    sum[3 * labels[i] + c] += lab[3 * i + c];
            }
            let shift = 0;
            for (let j = 0; j < k; j++)
                if (cnt[j])
                    for (let c = 0; c < 3; c++) {
                        const v = sum[3 * j + c] / cnt[j];
                        shift = Math.max(shift, Math.abs(v - cen[3 * j + c]));
                        cen[3 * j + c] = v;
                    }
            if (shift < 0.5)
                break;
        }
        let compact = 0;
        for (let i = 0; i < n; i++)
            compact += d2(i, cen, labels[i]);
        if (!best || compact < best.compact)
            best = { labels, compact };
    }
    const out = [];
    for (let c = 0; c < k; c++) {
        let m = 0;
        const s = [0, 0, 0];
        for (let i = 0; i < n; i++)
            if (best.labels[i] === c) {
                m++;
                for (let q = 0; q < 3; q++)
                    s[q] += px(i, q);
            }
        if (!m)
            continue;
        const hex = "#" + s.map((v) => Math.round(v / m).toString(16).padStart(2, "0")).join("");
        out.push({ hex, share: roundTo(m / n, 3) });
    }
    return out.sort((a, b) => b.share - a.share);
}
