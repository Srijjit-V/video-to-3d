"""Compute every worked example in docs/MATH.md from the real code, and draw the two charts.

    python scripts/math_examples.py            # prints the numbers, writes docs/img/*.svg
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import box_room  # noqa: E402
from vid3d import uncertainty  # noqa: E402
from vid3d.depth import align_disparity, metric_depth  # noqa: E402
from vid3d.geometry import View, backproject, ransac_plane, undistort_radial  # noqa: E402

IMG = ROOT / "docs" / "img"


def section(title: str) -> None:
    print(f"\n== {title}")


def backprojection() -> None:
    section("1. back-projection and lens undistortion")
    K = np.array([[500.0, 0, 320], [0, 500, 240], [0, 0, 1]])
    view = View("x", K, np.eye(3), np.zeros(3), 640, 480)
    depth = np.full((480, 640), 2.0, np.float32)
    rgb = np.zeros((480, 640, 3), np.uint8)
    p, _ = backproject(view, depth, rgb, stride=400)  # pixels (0,0), (0,400), (400,0), (400,400) -> centres +0.5
    print("world points for pixel centres (0.5,0.5),(400.5,0.5),(0.5,400.5),(400.5,400.5):\n", np.round(p, 4))
    norm = np.array([[(400.5 - 320) / 500, (300.5 - 240) / 500]])
    print("normalised coords of pixel (400,300):", np.round(norm, 4))
    k1 = -0.1
    xu = norm.copy()
    for i in range(6):
        r2 = (xu**2).sum(1, keepdims=True)
        xu = norm / (1 + k1 * r2)
        print(f"  fixed-point iteration {i + 1}: x_u = {np.round(xu[0], 6)}  r_u^2 = {float((xu**2).sum()):.6f}")
    back = xu * (1 + k1 * (xu**2).sum(1, keepdims=True))
    print("  forward check x_d = x_u (1 + k1 r_u^2):", np.round(back[0], 6), "(should equal", np.round(norm[0], 6), ")")
    print("  after 6 iterations error:", float(np.abs(undistort_radial(norm, k1) * (1 + k1 * (undistort_radial(norm, k1) ** 2).sum()) - norm).max()))
    X = np.append(undistort_radial(norm, k1)[0], 1.0) * 2.0
    print("  3D point at depth 2.0 m:", np.round(X, 4))


def disparity_fit() -> None:
    section("2. disparity to depth fit")
    rng = np.random.default_rng(4)
    a_true, b_true = 0.8, 0.05
    disp = rng.uniform(0.2, 1.2, 300)
    z = 1.0 / (a_true * disp + b_true)
    z = z * (1 + rng.normal(0, 0.01, z.shape))
    bad = rng.choice(300, 45, replace=False)  # 15% wrong matches
    z[bad] *= rng.uniform(1.5, 3.0, 45)
    a, b, inl = align_disparity(disp, z)
    print(f"truth a={a_true}, b={b_true}; fitted a={a:.4f}, b={b:.4f}; inlier share {inl:.3f}")
    ls = np.linalg.lstsq(np.stack([disp, np.ones_like(disp)], 1), 1 / z, rcond=None)[0]
    print(f"plain least squares on the same data: a={ls[0]:.4f}, b={ls[1]:.4f}")
    d = np.array([[0.4, 0.4, 0.4], [0.4, 0.4, 0.4], [0.4, 0.4, 0.4]])
    print("depth at disparity 0.4 from the fit:", round(float(metric_depth(d, a, b, 0.1, 20.0)[1, 1]), 3), "m (truth", round(1 / (a_true * 0.4 + b_true), 3), ")")
    depth = np.full((9, 9), 2.0)
    depth[:, 5:] = 2.4
    gy, gx = np.gradient(depth)
    rel = np.sqrt(gx**2 + gy**2) / depth
    print("flying-pixel test on a 2.0 -> 2.4 m step: relative gradient at the step columns =", np.round(rel[4, 4:6], 3), "(limit 0.04)")


def voxel_and_ransac() -> None:
    section("3. voxel size and RANSAC")
    for median_z in (1.2, 3.0):
        print(f"median COLMAP depth {median_z} m -> voxel {median_z / 200 * 100:.1f} cm")
    for w in (0.8, 0.5, 0.3):
        p_hit = 1 - (1 - w**3) ** 400
        print(f"inlier share {w}: chance that at least one of 400 random triples is all-inlier = {p_hit:.6f}")
    rng = np.random.default_rng(0)
    plane = np.c_[rng.uniform(0, 5, 2000), rng.normal(0, 0.01, 2000), rng.uniform(0, 4, 2000)]
    junk = rng.uniform([0, -1, 0], [5, 2, 4], (1000, 3))
    n, d, count = ransac_plane(np.concatenate([plane, junk]), 0.03)
    print("RANSAC + SVD on a level plane at y=0 with 1/3 junk: normal", np.round(n, 4), "d", round(float(d), 4), "inliers", count)


def scale_and_errors() -> None:
    section("4. scale")
    h, h_raw, l_raw, w_raw = 1.45, 0.62, 2.10, 1.70
    s = h / h_raw
    print(f"s = {h}/{h_raw} = {s:.4f}; L = {l_raw}*s = {l_raw * s:.2f} m; W = {w_raw}*s = {w_raw * s:.2f} m; area = {l_raw * w_raw * s * s:.2f} m2")
    print("phone really at 1.60 m (we assumed 1.45): L error", f"{(1.45 / 1.60 - 1) * 100:.1f}%", "area error", f"{((1.45 / 1.60) ** 2 - 1) * 100:.1f}%")
    print("height needed to be right within 5% area:", [round(1.5 * x, 3) for x in (0.95**0.5, 1.05**0.5)])


def monte_carlo_and_charts() -> None:
    section("5. ranges")
    room = box_room(5.0, 4.0, 2.6)
    rows = []
    for name, method, assumed in (("assumed 1.45 m", "camera held at ~1.45 m above floor (assumed)", 1.45),
                                  ("height given (1.5 m)", "camera height given: 1.5 m", 1.5),
                                  ("ceiling given (2.6 m)", "ceiling height = 2.6 m", 1.5)):
        k = assumed / 1.5
        est = uncertainty.estimate(room * k, 2.6 * k, method, floor_sigma_rel=0.01, seed=0)
        r = est["ranges"]
        rows.append((name, est["central"]["length_m"], r["length_m"], r["area_m2"], est["scale_sigma_rel"]))
        print(f"{name}: sigma_rel {est['scale_sigma_rel']}, length {est['central']['length_m']} -> {r['length_m']}, area {est['central']['area_m2']} -> {r['area_m2']}")
    IMG.mkdir(parents=True, exist_ok=True)
    chart_error_vs_height()
    chart_ranges(rows)


def svg_head(w, h, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{title}" '
            'font-family="system-ui, sans-serif" font-size="12">'
            '<style>text{fill:#1f2328}.grid{stroke:#d0d7de}.axis{stroke:#57606a}.accent{stroke:#0a69da;fill:none;stroke-width:2.5}'
            '.band{fill:#0a69da;opacity:.14}.dot{fill:#0a69da}.bar{fill:#0a69da}.mid{fill:#fff;stroke:#0a69da}'
            '@media(prefers-color-scheme:dark){text{fill:#e6edf3}.grid{stroke:#30363d}.axis{stroke:#8b949e}'
            '.accent{stroke:#58a6ff}.band{fill:#58a6ff}.dot,.bar{fill:#58a6ff}.mid{fill:#0d1117;stroke:#58a6ff}}</style>')


def chart_error_vs_height() -> None:
    w, h, ml, mr, mt, mb = 640, 340, 56, 20, 34, 48
    xs = np.linspace(1.1, 1.9, 81)
    err = ((1.45 / 1.5) * 0 + (xs / 1.5) ** 2 - 1) * 100  # area error if we assume `xs` and the truth is 1.5
    # assumed height x (pipeline) vs true 1.5:  measured/true = (x/1.5)^2
    X = lambda v: ml + (v - 1.1) / 0.8 * (w - ml - mr)  # noqa: E731
    Y = lambda v: mt + (60 - v) / 100 * (h - mt - mb)  # noqa: E731
    o = [svg_head(w, h, "Area error against the camera height that was assumed")]
    o.append(f'<text x="{ml}" y="20" font-weight="600">Area error if the phone was really at 1.5 m</text>')
    for v in range(-40, 61, 20):
        o.append(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text x="{ml - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:+d}%</text>')
    for v in (1.1, 1.3, 1.5, 1.7, 1.9):
        o.append(f'<text x="{X(v):.1f}" y="{h - mb + 18}" text-anchor="middle">{v:.1f}</text>')
    o.append(f'<text x="{(ml + w - mr) / 2:.0f}" y="{h - 8}" text-anchor="middle">camera height assumed by the program (m)</text>')
    o.append(f'<rect class="band" x="{X(1.45 * (1 - 0.132)):.1f}" y="{mt}" width="{X(1.45 * 1.132) - X(1.45 * (1 - 0.132)):.1f}" height="{h - mt - mb}"/>')
    pts = " ".join(f"{X(a):.1f},{Y(e):.1f}" for a, e in zip(xs, err, strict=True))
    o.append(f'<polyline class="accent" points="{pts}"/>')
    o.append(f'<circle class="dot" cx="{X(1.45):.1f}" cy="{Y(((1.45 / 1.5) ** 2 - 1) * 100):.1f}" r="4.5"/>')
    o.append(f'<text x="{X(1.45) + 8:.1f}" y="{Y(((1.45 / 1.5) ** 2 - 1) * 100) + 16:.1f}">default 1.45 m: {((1.45 / 1.5) ** 2 - 1) * 100:+.1f}%</text>')
    o.append(f'<text x="{X(1.45 * 1.132) - 4:.1f}" y="{mt + 14}" text-anchor="end">shaded: 90% of phones held at 1.26 to 1.64 m</text>')
    o.append("</svg>")
    (IMG / "area-error-vs-camera-height.svg").write_text("\n".join(o))


def chart_ranges(rows) -> None:
    w, h, ml, mr, mt, mb = 640, 220, 150, 24, 34, 40
    lo_v, hi_v = 12.0, 30.0
    X = lambda v: ml + (v - lo_v) / (hi_v - lo_v) * (w - ml - mr)  # noqa: E731
    o = [svg_head(w, h, "90 percent range of the room area by where the scale came from")]
    o.append('<text x="16" y="20" font-weight="600">Area range for a 5.0 x 4.0 m room (true area 20 m²)</text>')
    for v in range(12, 31, 3):
        o.append(f'<line class="grid" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{mt}" y2="{h - mb}"/>'
                 f'<text x="{X(v):.1f}" y="{h - mb + 16}" text-anchor="middle">{v}</text>')
    o.append(f'<line class="axis" x1="{X(20):.1f}" x2="{X(20):.1f}" y1="{mt}" y2="{h - mb}" stroke-dasharray="4 3"/>')
    o.append(f'<text x="{X(20) + 4:.1f}" y="{mt + 11}">truth 20</text>')
    o.append(f'<text x="{(ml + w - mr) / 2:.0f}" y="{h - 6}" text-anchor="middle">area (m²)</text>')
    for i, (name, _c, _l, area, _s) in enumerate(rows):
        y = mt + 24 + i * 50
        o.append(f'<text x="{ml - 10}" y="{y + 4}" text-anchor="end">{name}</text>')
        o.append(f'<rect class="bar" x="{X(area[0]):.1f}" y="{y - 8}" width="{X(area[1]) - X(area[0]):.1f}" height="16" rx="3"/>')
        o.append(f'<text x="{X(area[1]) + 6:.1f}" y="{y + 4}">{area[0]} to {area[1]}</text>')
    o.append("</svg>")
    (IMG / "area-range-by-scale-source.svg").write_text("\n".join(o))


if __name__ == "__main__":
    backprojection()
    disparity_fit()
    voxel_and_ransac()
    scale_and_errors()
    monte_carlo_and_charts()
