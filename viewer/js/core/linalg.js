// Small numeric helpers that mirror the numpy calls used by the Python reference (src/vid3d).
export function sortedCopy(a) {
    const s = Float64Array.from(a);
    s.sort();
    return s;
}
/** numpy.median: mean of the two middle values for an even count. NaN for an empty input. */
export function median(a) {
    const n = a.length;
    if (!n)
        return NaN;
    const s = sortedCopy(a);
    return n % 2 ? s[(n - 1) / 2] : 0.5 * (s[n / 2 - 1] + s[n / 2]);
}
/** numpy.percentile (linear interpolation) for one q in 0..100. */
export function percentile(a, q) {
    return percentiles(a, [q])[0];
}
export function percentiles(a, qs) {
    const s = sortedCopy(a), n = s.length;
    if (!n)
        return qs.map(() => NaN);
    return qs.map((q) => {
        const pos = (q / 100) * (n - 1), lo = Math.floor(pos), hi = Math.min(n - 1, lo + 1);
        return s[lo] + (s[hi] - s[lo]) * (pos - lo);
    });
}
export const mean = (a) => { let s = 0; for (let i = 0; i < a.length; i++)
    s += a[i]; return s / a.length; };
export const std = (a) => { const m = mean(a); let s = 0; for (let i = 0; i < a.length; i++)
    s += (a[i] - m) ** 2; return Math.sqrt(s / a.length); };
/** A seeded generator (mulberry32). Not numpy's: results that depend on random draws agree statistically, not bit for bit. */
export class Rng {
    s;
    constructor(seed = 0) { this.s = (seed >>> 0) + 0x6d2b79f5; }
    next() {
        this.s = (this.s + 0x6d2b79f5) >>> 0;
        let t = this.s;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    uniform(lo, hi) { return lo + (hi - lo) * this.next(); }
    int(n) { return Math.floor(this.next() * n); }
    normal(sd = 1) {
        const u = 1 - this.next(), v = this.next();
        return sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    }
    /** k distinct indices out of n (partial Fisher-Yates). */
    choice(n, k) {
        const k2 = Math.min(k, n);
        const idx = new Int32Array(n);
        for (let i = 0; i < n; i++)
            idx[i] = i;
        for (let i = 0; i < k2; i++) {
            const j = i + this.int(n - i);
            const t = idx[i];
            idx[i] = idx[j];
            idx[j] = t;
        }
        return idx.slice(0, k2);
    }
}
/** numpy.arange for floats: ceil((stop - start) / step) values start + i * step. */
export function arange(start, stop, step) {
    const n = Math.max(0, Math.ceil((stop - start) / step));
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++)
        out[i] = start + i * step;
    return out;
}
/** numpy.histogram with an explicit, increasing edge array: bins [e_i, e_i+1), the last one closed. */
export function histogramEdges(values, edges) {
    const m = edges.length - 1, counts = new Float64Array(Math.max(0, m));
    if (m < 1)
        return counts;
    const first = edges[0], last = edges[m];
    for (let k = 0; k < values.length; k++) {
        const v = values[k];
        if (!(v >= first && v <= last))
            continue;
        let lo = 0, hi = m; // largest i with edges[i] <= v, capped at m - 1
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1;
            if (edges[mid] <= v)
                lo = mid;
            else
                hi = mid - 1;
        }
        counts[Math.min(lo, m - 1)]++;
    }
    return counts;
}
/** numpy.histogram(values, bins=n, range=(lo, hi)): equal-width bins, values outside the range ignored. */
export function histogramRange(values, n, lo, hi) {
    const counts = new Float64Array(n), w = hi - lo;
    for (let k = 0; k < values.length; k++) {
        const v = values[k];
        if (!(v >= lo && v <= hi))
            continue;
        counts[Math.min(n - 1, Math.floor(((v - lo) / w) * n))]++;
    }
    return counts;
}
export const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const norm3 = (a) => Math.hypot(a[0], a[1], a[2]);
export const unit3 = (a) => { const n = norm3(a); return [a[0] / n, a[1] / n, a[2] / n]; };
/** Eigenvector of the smallest eigenvalue of a symmetric 3x3 matrix (row-major, 9 numbers), by Jacobi rotations.
 *  This is the right singular vector SVD gives for the smallest singular value of centred points. */
export function smallestEigenvector3(m) {
    const a = m.slice();
    const v = [1, 0, 0, 0, 1, 0, 0, 0, 1];
    for (let sweep = 0; sweep < 50; sweep++) {
        const off = Math.abs(a[1]) + Math.abs(a[2]) + Math.abs(a[5]);
        if (off < 1e-14 * (Math.abs(a[0]) + Math.abs(a[4]) + Math.abs(a[8]) + 1e-300))
            break;
        for (const [p, q] of [[0, 1], [0, 2], [1, 2]]) {
            const apq = a[p * 3 + q];
            if (Math.abs(apq) < 1e-300)
                continue;
            const theta = (a[q * 3 + q] - a[p * 3 + p]) / (2 * apq);
            const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
            const c = 1 / Math.sqrt(t * t + 1), s = t * c;
            for (let k = 0; k < 3; k++) { // rotate columns p, q
                const akp = a[k * 3 + p], akq = a[k * 3 + q];
                a[k * 3 + p] = c * akp - s * akq;
                a[k * 3 + q] = s * akp + c * akq;
            }
            for (let k = 0; k < 3; k++) { // rotate rows p, q
                const apk = a[p * 3 + k], aqk = a[q * 3 + k];
                a[p * 3 + k] = c * apk - s * aqk;
                a[q * 3 + k] = s * apk + c * aqk;
            }
            for (let k = 0; k < 3; k++) {
                const vkp = v[k * 3 + p], vkq = v[k * 3 + q];
                v[k * 3 + p] = c * vkp - s * vkq;
                v[k * 3 + q] = s * vkp + c * vkq;
            }
        }
    }
    let best = 0;
    for (const i of [1, 2])
        if (a[i * 3 + i] < a[best * 3 + best])
            best = i;
    return [v[best], v[3 + best], v[6 + best]];
}
