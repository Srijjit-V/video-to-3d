"""How wrong could the numbers be? Ranges and a plain-language confidence.

The model is derived in docs/MATH.md. In short, every length in the room is `extent x scale`, and the scale
`s = h / h_raw` comes from one assumed (or given) camera height h and the fitted floor height h_raw.
We draw the scale error and the wall-position error many times (Monte Carlo) and report the 5th to 95th
percentile, so "4.0 m" becomes "3.8 to 4.2 m".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from . import floorplan

# Relative standard deviation of the scale, by where it came from. "assumed": a phone held anywhere
# between chest and eye level is 1.2 to 1.7 m, about +-17% (2 sigma) around the 1.45 m default.
SCALE_SIGMA_REL = {"assumed": 0.08, "given": 0.03, "ceiling": 0.02}
THRESHOLD_RANGE = (0.15, 0.45)  # wall-peak threshold is varied around the default 0.3
CAMERA_HEIGHT_RELATIVE_LIMIT = 0.15
MAX_WALL_POINTS = 6_000


def scale_source(method: str) -> str:
    if method.startswith("ceiling height ="):
        return "ceiling"
    if "(assumed)" in method:
        return "assumed"
    return "given"


def _interval(values: np.ndarray, digits: int) -> list[float]:
    lo, hi = np.percentile(values, [5, 95])
    return [round(float(lo), digits), round(float(hi), digits)]


def format_range(r: list, unit: str) -> str:
    """'3.8 to 4.2 m', or 'at least 2.7 m' when there is no upper end."""
    return f"at least {r[0]} {unit}" if r[1] is None else f"{r[0]} to {r[1]} {unit}"


def area_half_width_rel(ranges: dict | None) -> float | None:
    """Half the width of the area range relative to its middle; None when there is no two-sided range."""
    if not ranges or ranges["area_m2"][1] is None:
        return None
    lo, hi = ranges["area_m2"]
    return (hi - lo) / 2 / max(1e-9, (hi + lo) / 2)


def estimate(points: np.ndarray, room_height: float | None, method: str, floor_sigma_rel: float,
             n: int = 400, seed: int = 0) -> dict:
    """Central values and 90% ranges for the room. `points` are metric, floor at y = 0, walls on the axes."""
    room = floorplan.analyze(points, room_height)
    src = scale_source(method)
    sigma = float(np.hypot(SCALE_SIGMA_REL[src], floor_sigma_rel))
    out: dict = {"scale_source": src, "scale_sigma_rel": round(sigma, 3), "samples": n}
    if not room or room.get("incomplete"):
        out.update(central=None, ranges=None)
        return out

    rng = np.random.default_rng(seed)
    xz = floorplan.wall_points(points, room_height)
    if len(xz) > MAX_WALL_POINTS:
        xz = xz[rng.choice(len(xz), MAX_WALL_POINTS, replace=False)]
    lengths, widths = np.empty(n), np.empty(n)
    for i in range(n):
        sample = xz[rng.integers(0, len(xz), len(xz))]  # bootstrap: which points happened to be seen
        frac = rng.uniform(*THRESHOLD_RANGE)  # how strict "wall" is
        x0, x1 = floorplan._extent(sample[:, 0], frac)
        z0, z1 = floorplan._extent(sample[:, 1], frac)
        lengths[i], widths[i] = x1 - x0, z1 - z0
    # One scale error is shared by every length: s_true / s_used = (h_true / h) * (h_raw / h_raw_true).
    f = np.clip((1 + rng.normal(0, SCALE_SIGMA_REL[src], n)) / (1 + rng.normal(0, floor_sigma_rel, n)), 0.5, 2.0)
    lengths, widths = lengths * f, widths * f
    ranges: dict[str, Any] = {
        "length_m": _interval(lengths, 2),
        "width_m": _interval(widths, 2),
        "area_m2": _interval(lengths * widths, 1),
        "height_m": _interval(room_height * f, 2) if room_height else None,
    }
    if room.get("missing_wall"):
        # A wall was never filmed: the true room is at least this big, and there is no honest upper end.
        axis = room["missing_axis"]
        ranges[axis] = [ranges[axis][0], None]
        ranges["area_m2"] = [ranges["area_m2"][0], None]
        out["lower_bound_only"] = [axis, "area_m2"]
    out.update(central={k: room.get(k) for k in ("length_m", "width_m", "area_m2", "height_m")}, ranges=ranges)
    return out


def floor_sigma_rel(find_floor: Callable, points: np.ndarray, cams: np.ndarray, up_hint: np.ndarray,
                    draws: int = 12, seed: int = 0, fraction: float = 0.5) -> float:
    """Relative spread of the fitted camera height when the floor is re-fitted on random halves of the cloud."""
    rng = np.random.default_rng(seed)
    heights = []
    for _ in range(draws):
        take = rng.choice(len(points), min(40_000, max(100, int(fraction * len(points)))), replace=False)
        try:
            heights.append(float(find_floor(points[take], cams, up_hint).cam_height_raw))
        except RuntimeError:
            continue
    if len(heights) < 3:
        return 0.05  # the floor was hard to fit at all: say so with a wide value instead of pretending
    return float(np.std(heights) / abs(np.mean(heights)))


def camera_height_consistency(heights_m: np.ndarray) -> dict:
    """The model has one scale; if the phone really moved up and down a lot, one scale cannot fit everywhere."""
    h = np.asarray(heights_m, float)
    med, spread = float(np.median(h)), float(np.std(h))
    rel = spread / med if med > 0 else 1.0
    return {"median_m": round(med, 3), "spread_m": round(spread, 3), "relative": round(rel, 3),
            "inconsistent": rel > CAMERA_HEIGHT_RELATIVE_LIMIT}


def confidence(method: str, registered_share: float, room: dict, area_half_width_rel: float | None,
               height_inconsistent: bool) -> dict:
    """A 0 to 100 score with the reasons, in words. High 75+, medium 50 to 74, low below."""
    score, reasons = 100.0, []
    src = scale_source(method)
    if src == "assumed":
        score -= 25
        reasons.append("Real-world scale is a guess from typical phone height.")
    elif src == "given":
        score -= 10
        reasons.append("Scale depends on the camera height you gave.")
    else:
        score -= 5
        reasons.append("Scale comes from the ceiling height you gave.")
    if registered_share < 0.8:
        score -= min(25.0, (0.8 - registered_share) * 100)
        reasons.append(f"Only {round(registered_share * 100)}% of the frames could be placed.")
    if room.get("incomplete"):
        score = min(score, 20.0)
        reasons.append("Opposite walls were not both captured, so there is no size to trust.")
    elif room.get("missing_wall"):
        score = min(score, 35.0)
        reasons.append("A wall was never filmed, so the room is bigger than what was measured.")
    elif room.get("rectangular") is False:
        score -= 20
        reasons.append("The outline is not a simple rectangle, so the area is an upper bound.")
    if area_half_width_rel is not None:
        if area_half_width_rel > 0.25:
            score -= 30
            reasons.append("The area range is very wide.")
        elif area_half_width_rel > 0.15:
            score -= 15
            reasons.append("The area range is fairly wide.")
    if height_inconsistent:
        score -= 10
        reasons.append("The phone height changed a lot during the walk, so one scale fits less well.")
    score = max(0, min(100, round(score)))
    label = "high" if score >= 75 else "medium" if score >= 50 else "low"
    words = {"high": "You can rely on these sizes within the ranges shown.",
             "medium": "Good for planning. Calibrate with something you measured before relying on exact values.",
             "low": "Treat these as a rough idea only."}[label]
    return {"score": score, "label": label, "summary": words, "reasons": reasons}
