// Point-cloud maths: back-projection, fusion, floor finding, scale frame (port of src/vid3d/geometry.py).
// Points are flat arrays [x0, y0, z0, x1, ...]. Rotations are 9 numbers, row-major.
import { Rng, arange, cross3, dot3, histogramEdges, median, norm3, percentile, smallestEigenvector3, unit3 } from "./linalg.js";
/** Camera centre in the world: -R^T t. */
export function viewCenter(v) {
    return [0, 1, 2].map((j) => -(v.R[j] * v.t[0] + v.R[3 + j] * v.t[1] + v.R[6 + j] * v.t[2]));
}
/** World direction of the image's "up" (image y grows downward): R^T (0, -1, 0). */
export function viewUp(v) { return [-v.R[3], -v.R[4], -v.R[5]]; }
/** Invert COLMAP's SIMPLE_RADIAL on normalised coordinates: x_d = x_u (1 + k1 r_u^2). */
export function undistortRadial(x, y, k1, iters = 6) {
    let xu = x, yu = y;
    for (let i = 0; i < iters; i++) {
        const f = 1 + k1 * (xu * xu + yu * yu);
        xu = x / f;
        yu = y / f;
    }
    return [xu, yu];
}
/** Dense depth map (row-major h x w, NaN = none) -> world points and colours, every `stride` pixels. */
export function backproject(view, depth, rgb, h, w, stride = 4, k1 = 0) {
    const pts = [], cols = [];
    for (let v = 0; v < h; v += stride)
        for (let u = 0; u < w; u += stride) {
            const d = depth[v * w + u];
            if (!Number.isFinite(d))
                continue;
            let x = (u + 0.5 - view.cx) / view.fx, y = (v + 0.5 - view.cy) / view.fy;
            if (k1)
                [x, y] = undistortRadial(x, y, k1);
            const c = [x * d - view.t[0], y * d - view.t[1], d - view.t[2]]; // (Xc - t) @ R
            for (let j = 0; j < 3; j++)
                pts.push(c[0] * view.R[j] + c[1] * view.R[3 + j] + c[2] * view.R[6 + j]);
            const o = (v * w + u) * 3;
            cols.push(rgb[o], rgb[o + 1], rgb[o + 2]);
        }
    return { points: Float32Array.from(pts), colors: Uint8Array.from(cols) };
}
/** Voxel-average the cloud, keep voxels seen by >= minViews frames. `frames` must be non-decreasing (as the pipeline makes it).
 *  Output order follows the voxel key, like numpy.unique. */
export function fuse(points, colors, frames, voxel, minViews = 2) {
    const n = frames.length;
    if (!(voxel > 0) || !Number.isFinite(voxel))
        throw new Error("The fusion voxel size must be a positive number.");
    if (!n)
        return { points: new Float32Array(0), colors: new Uint8Array(0), views: new Uint8Array(0) };
    const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
    const key = new Float64Array(n * 3);
    for (let i = 0; i < n; i++)
        for (let j = 0; j < 3; j++) {
            const k = Math.floor(points[3 * i + j] / voxel);
            if (!Number.isFinite(k))
                throw new Error("The cloud is too spread out (or contains invalid points) to fuse.");
            key[3 * i + j] = k;
            if (k < mn[j])
                mn[j] = k;
            if (k > mx[j])
                mx[j] = k;
        }
    const d1 = mx[1] - mn[1] + 1, d2 = mx[2] - mn[2] + 1, span = (mx[0] - mn[0] + 1) * d1 * d2;
    if (!Number.isFinite(span) || span > 2 ** 52)
        throw new Error("The cloud is too spread out (or contains invalid points) to fuse.");
    const cells = new Map();
    let prev = -Infinity;
    for (let i = 0; i < n; i++) {
        if (frames[i] < prev)
            throw new Error("frame ids must be non-decreasing");
        prev = frames[i];
        const flat = ((key[3 * i] - mn[0]) * d1 + (key[3 * i + 1] - mn[1])) * d2 + (key[3 * i + 2] - mn[2]);
        let c = cells.get(flat);
        if (!c) {
            c = { n: 0, sum: [0, 0, 0], col: [0, 0, 0], views: 0, last: -1 };
            cells.set(flat, c);
        }
        c.n++;
        for (let j = 0; j < 3; j++) {
            c.sum[j] += points[3 * i + j];
            c.col[j] += colors[3 * i + j];
        }
        if (c.last !== frames[i]) {
            c.views++;
            c.last = frames[i];
        }
    }
    const flats = [...cells.keys()].filter((f) => cells.get(f).views >= minViews).sort((a, b) => a - b);
    const P = new Float32Array(flats.length * 3), C = new Uint8Array(flats.length * 3), V = new Uint8Array(flats.length);
    flats.forEach((f, i) => {
        const c = cells.get(f);
        for (let j = 0; j < 3; j++) {
            P[3 * i + j] = c.sum[j] / c.n;
            C[3 * i + j] = Math.trunc(c.col[j] / c.n);
        }
        V[i] = Math.min(255, c.views);
    });
    return { points: P, colors: C, views: V };
}
/** Best plane n.x + d = 0 (unit n), optionally only near a normal hint; refined by least squares on its inliers. */
export function ransacPlane(pts, thresh, iters = 400, normalHint = null, maxAngleDeg = 25, seed = 0) {
    const m = Math.floor(pts.length / 3);
    if (m < 3)
        return null;
    const rng = new Rng(seed), cosLim = Math.cos((maxAngleDeg * Math.PI) / 180);
    let best = null;
    const P = (i) => [pts[3 * i], pts[3 * i + 1], pts[3 * i + 2]];
    for (let it = 0; it < iters; it++) {
        const [ia, ib, ic] = rng.choice(m, 3), a = P(ia), b = P(ib), c = P(ic);
        let n = cross3([b[0] - a[0], b[1] - a[1], b[2] - a[2]], [c[0] - a[0], c[1] - a[1], c[2] - a[2]]);
        const nn = norm3(n);
        if (nn < 1e-12)
            continue;
        n = n.map((v) => v / nn);
        if (normalHint) {
            if (dot3(n, normalHint) < 0)
                n = n.map((v) => -v);
            if (dot3(n, normalHint) < cosLim)
                continue;
        }
        const d = -dot3(n, a);
        let count = 0;
        for (let i = 0; i < m; i++)
            if (Math.abs(pts[3 * i] * n[0] + pts[3 * i + 1] * n[1] + pts[3 * i + 2] * n[2] + d) < thresh)
                count++;
        if (!best || count > best.count)
            best = { n, d, count };
    }
    if (!best)
        return null;
    const { n, d } = best;
    const inl = [];
    for (let i = 0; i < m; i++)
        if (Math.abs(pts[3 * i] * n[0] + pts[3 * i + 1] * n[1] + pts[3 * i + 2] * n[2] + d) < thresh)
            inl.push(i);
    const mean = [0, 0, 0];
    for (const i of inl)
        for (let j = 0; j < 3; j++)
            mean[j] += pts[3 * i + j] / inl.length;
    const cov = new Array(9).fill(0);
    for (const i of inl) {
        const q = [pts[3 * i] - mean[0], pts[3 * i + 1] - mean[1], pts[3 * i + 2] - mean[2]];
        for (let r = 0; r < 3; r++)
            for (let c = 0; c < 3; c++)
                cov[r * 3 + c] += q[r] * q[c];
    }
    let n2 = smallestEigenvector3(cov);
    if (dot3(n2, n) < 0)
        n2 = n2.map((v) => -v);
    return { n: n2, d: -dot3(n2, mean), count: inl.length };
}
/** Heights of dense horizontal layers in a height histogram (floor, tabletops, ceiling). */
export function layerPeaks(h, binW, minFrac = 0.3) {
    if (h.length < 50)
        return { heights: [], counts: [] };
    let lo = Infinity, hi = -Infinity;
    for (const v of h) {
        if (v < lo)
            lo = v;
        if (v > hi)
            hi = v;
    }
    const edges = arange(lo, hi + 2 * binW, binW), raw = histogramEdges(h, edges), m = raw.length;
    const cnt = new Float64Array(m);
    for (let i = 0; i < m; i++)
        cnt[i] = 0.25 * (i > 0 ? raw[i - 1] : 0) + 0.5 * raw[i] + 0.25 * (i < m - 1 ? raw[i + 1] : 0);
    let mx = 0;
    for (const v of cnt)
        if (v > mx)
            mx = v;
    const heights = [], counts = [];
    for (let i = 0; i < m; i++) {
        if (cnt[i] >= (i < m - 1 ? cnt[i + 1] : 0) && cnt[i] >= (i > 0 ? cnt[i - 1] : 0) && cnt[i] >= minFrac * mx) {
            heights.push(edges[i] + binW / 2);
            counts.push(cnt[i]);
        }
    }
    return { heights, counts };
}
function interiorFraction(layer, walls, up, center) {
    const radial = (p) => {
        const q = [p[0] - center[0], p[1] - center[1], p[2] - center[2]], s = dot3(q, up);
        return Math.hypot(q[0] - s * up[0], q[1] - s * up[1], q[2] - s * up[2]);
    };
    if (walls.length < 20 || !layer.length)
        return 0;
    const lim = 0.6 * median(walls.map(radial));
    return layer.filter((p) => radial(p) < lim).length / layer.length;
}
const col = (a, i) => [a[3 * i], a[3 * i + 1], a[3 * i + 2]];
/** Floor = the lowest dense horizontal layer below the cameras, re-levelled with its fitted normal (up to 4 times). */
export function findFloor(points, cams, upHint) {
    const n = Math.floor(points.length / 3), nc = Math.floor(cams.length / 3);
    let up = unit3(upHint);
    const heights = (u) => { const h = new Float64Array(n); for (let i = 0; i < n; i++)
        h[i] = points[3 * i] * u[0] + points[3 * i + 1] * u[1] + points[3 * i + 2] * u[2]; return h; };
    let h = heights(up);
    const binW = (percentile(h, 99) - percentile(h, 1)) / 150;
    let d = null;
    for (let it = 0; it < 4; it++) {
        h = heights(up);
        const camH = median(Array.from({ length: nc }, (_, i) => dot3(col(cams, i), up)));
        const belowIdx = [];
        for (let i = 0; i < n; i++)
            if (h[i] < camH - 3 * binW)
                belowIdx.push(i);
        const { heights: peaks } = layerPeaks(Float64Array.from(belowIdx, (i) => h[i]), binW);
        if (!peaks.length)
            throw new Error("Could not find a floor. Make sure the floor is visible in the video.");
        const floorH = Math.min(...peaks), layer = [];
        for (const i of belowIdx)
            if (Math.abs(h[i] - floorH) < 3 * binW)
                layer.push(points[3 * i], points[3 * i + 1], points[3 * i + 2]);
        const plane = ransacPlane(layer, binW, 400, up, 15);
        if (!plane)
            throw new Error("Could not fit the floor plane.");
        const moved = (Math.acos(Math.max(-1, Math.min(1, dot3(plane.n, up)))) * 180) / Math.PI;
        up = plane.n;
        d = plane.d;
        if (moved < 0.2)
            break;
    }
    if (d === null)
        throw new Error("The floor could not be found in this video.");
    const camHeight = median(Array.from({ length: nc }, (_, i) => dot3(col(cams, i), up) + d));
    if (camHeight <= 0)
        throw new Error("Floor detection failed (cameras below detected floor).");
    h = heights(up);
    for (let i = 0; i < n; i++)
        h[i] += d;
    const aboveIdx = [];
    let floorCount = 0;
    for (let i = 0; i < n; i++) {
        if (h[i] > camHeight + 3 * binW)
            aboveIdx.push(i);
        if (Math.abs(h[i]) < 2 * binW)
            floorCount++;
    }
    let ceiling = null;
    if (aboveIdx.length > 200) {
        const { heights: peaks } = layerPeaks(Float64Array.from(aboveIdx, (i) => h[i]), binW, 0.5);
        if (peaks.length) {
            const top = Math.max(...peaks), onTop = [], walls = [];
            for (let i = 0; i < n; i++) {
                if (Math.abs(h[i] - top) < 2 * binW)
                    onTop.push(col(points, i));
                if (Math.abs(h[i] - camHeight) < 3 * binW)
                    walls.push(col(points, i));
            }
            const center = [0, 1, 2].map((j) => median(Array.from({ length: nc }, (_, i) => cams[3 * i + j])));
            if (top > 1.2 * camHeight && onTop.length > 0.1 * floorCount && interiorFraction(onTop, walls, up, center) > 0.3)
                ceiling = top;
        }
    }
    return { up, floorD: d, camHeightRaw: camHeight, ceilingHeightRaw: ceiling };
}
/** Rotation (rows = new axes) and origin that put the floor at y = 0 with +y up. */
export function floorFrame(floor, cams) {
    const y = floor.up, ref = Math.abs(y[0]) < 0.9 ? [1, 0, 0] : [0, 0, 1], s = dot3(ref, y);
    const x = unit3([ref[0] - y[0] * s, ref[1] - y[1] * s, ref[2] - y[2] * s]), z = cross3(x, y);
    const nc = Math.floor(cams.length / 3), c = [0, 0, 0];
    for (let i = 0; i < nc; i++)
        for (let j = 0; j < 3; j++)
            c[j] += cams[3 * i + j] / nc;
    const k = dot3(y, c) + floor.floorD;
    return { Rw: [...x, ...y, ...z], origin: [c[0] - y[0] * k, c[1] - y[1] * k, c[2] - y[2] * k] };
}
/** Rotate (x, z) pairs by `deg`: points @ R^T with R = [[cos, -sin], [sin, cos]]. In place on a flat [x, z, ...] array. */
export function yawAlign(xz, deg) {
    const a = (deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a), out = new Float64Array(xz.length);
    for (let i = 0; i < xz.length; i += 2) {
        out[i] = xz[i] * c - xz[i + 1] * s;
        out[i + 1] = xz[i] * s + xz[i + 1] * c;
    }
    return out;
}
