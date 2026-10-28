"""Stage 6: top-down analysis — room size, area and a floor-plan image.

Input points are metric with the floor at y=0 and +y up.
"""

from __future__ import annotations

import cv2
import numpy as np

from .geometry import yaw_align

CELL = 0.05  # metres per grid cell
MIN_ROOM_SIDE_M = 1.0  # anything narrower means a wall pair wasn't captured


def wall_points(points: np.ndarray, room_height: float | None) -> np.ndarray:
    top = (room_height - 0.2) if room_height else 2.1
    y = points[:, 1]
    return points[(y > 0.3) & (y < top)][:, [0, 2]]


def dominant_yaw(points: np.ndarray, room_height: float | None) -> float:
    """Angle (deg) that makes the walls line up with the x/z axes."""
    xz = wall_points(points, room_height)
    if len(xz) < 100:
        return 0.0
    if len(xz) > 40000:
        xz = xz[np.random.default_rng(0).choice(len(xz), 40000, replace=False)]
    xz = xz - xz.mean(0)

    def peakiness(deg):
        # When walls line up with an axis, their points pile into a few bins,
        # so the sum of squared bin counts is highest.

        r = yaw_align(xz, -deg)  # same convention the pipeline uses to undo the yaw
        score = 0.0
        for k in range(2):
            h, _ = np.histogram(r[:, k], bins=np.arange(r[:, k].min(), r[:, k].max() + CELL, CELL / 2))
            score += float((h.astype(np.float64) ** 2).sum())
        return score

    coarse = np.arange(0, 90, 1.0)
    best = coarse[np.argmax([peakiness(d) for d in coarse])]
    fine = np.arange(best - 1, best + 1.01, 0.1)
    return float(fine[np.argmax([peakiness(d) for d in fine])])


def _extent(coord: np.ndarray) -> tuple[float, float]:
    """Room span along one axis: outermost strong wall peaks in a 1-D histogram."""
    lo, hi = np.percentile(coord, [0.5, 99.5])
    bins = np.arange(lo - CELL, hi + 2 * CELL, CELL)
    h, e = np.histogram(coord, bins)
    strong = np.nonzero(h >= 0.3 * h.max())[0]
    return float(e[strong[0]] + CELL / 2), float(e[strong[-1]] + CELL / 2)


def analyze(points: np.ndarray, room_height: float | None) -> dict:
    xz = wall_points(points, room_height)
    if len(xz) < 100:
        return {}
    x0, x1 = _extent(xz[:, 0])
    z0, z1 = _extent(xz[:, 1])
    length, width = x1 - x0, z1 - z0
    if min(length, width) < MIN_ROOM_SIDE_M:
        # Walls were only seen on one side along some direction: no honest size.
        return {"incomplete": True,
                "reason": "Opposite walls were not both captured, so the room size can't be measured."}
    area = length * width
    return {
        "rect_m": [x0, z0, x1, z1],
        "length_m": round(length, 3),
        "width_m": round(width, 3),
        "height_m": round(room_height, 3) if room_height else None,
        "area_m2": round(area, 2),
        "area_ft2": round(area * 10.7639, 1),
    }


def render(points: np.ndarray, colors: np.ndarray, cams: np.ndarray, room: dict, room_height, path) -> None:
    """Draw a floor-plan PNG with a 1 m grid, camera path and dimensions."""
    px = 100  # pixels per metre
    xz = points[:, [0, 2]]
    lo = np.percentile(xz, 0.5, 0) - 0.6
    hi = np.percentile(xz, 99.5, 0) + 0.6
    W, H = (np.ceil((hi - lo) * px)).astype(int)
    img = np.full((H, W, 3), 24, np.uint8)

    def to_px(p):
        return np.round((np.asarray(p) - lo) * px).astype(int)

    for gx in np.arange(np.ceil(lo[0]), hi[0], 1.0):
        cv2.line(img, tuple(to_px([gx, lo[1]])), tuple(to_px([gx, hi[1]])), (45, 45, 45), 1)
    for gz in np.arange(np.ceil(lo[1]), hi[1], 1.0):
        cv2.line(img, tuple(to_px([lo[0], gz])), tuple(to_px([hi[0], gz])), (45, 45, 45), 1)

    y = points[:, 1]
    fl = np.abs(y) < 0.06
    p = to_px(xz[fl])
    ok = (p[:, 0] >= 0) & (p[:, 1] >= 0) & (p[:, 0] < W) & (p[:, 1] < H)
    img[p[ok, 1], p[ok, 0]] = (colors[fl][ok][:, ::-1] * 0.6).astype(np.uint8)

    w = wall_points(points, room_height)
    p = to_px(w)
    ok = (p[:, 0] >= 0) & (p[:, 1] >= 0) & (p[:, 0] < W) & (p[:, 1] < H)
    img[p[ok, 1], p[ok, 0]] = (235, 235, 235)

    cp = to_px(cams[:, [0, 2]])
    cv2.polylines(img, [cp.reshape(-1, 1, 2)], False, (0, 140, 255), 2, cv2.LINE_AA)

    if room.get("rect_m"):
        x0, z0, x1, z1 = room["rect_m"]
        cv2.rectangle(img, tuple(to_px([x0, z0])), tuple(to_px([x1, z1])), (90, 200, 120), 2)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(img, f"{room['length_m']:.2f} m", tuple(to_px([(x0 + x1) / 2 - 0.3, z0 - 0.15])),
                    font, 0.7, (90, 200, 120), 2, cv2.LINE_AA)
        cv2.putText(img, f"{room['width_m']:.2f} m", tuple(to_px([x1 + 0.08, (z0 + z1) / 2])),
                    font, 0.7, (90, 200, 120), 2, cv2.LINE_AA)
        cv2.putText(img, f"~{room['area_m2']} m2 / {room['area_ft2']} ft2 (estimate)", (12, H - 14),
                    font, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.line(img, (12, 20), (12 + px, 20), (200, 200, 200), 2)
    cv2.putText(img, "1 m", (12, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), img)
