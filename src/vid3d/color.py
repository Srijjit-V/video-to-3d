"""Colour handling: even out exposure between frames, and find dominant colours."""

from __future__ import annotations

import cv2
import numpy as np

GAIN_LIMITS = (0.75, 1.35)  # keep the correction gentle
TARGET_LUMA = (90.0, 150.0)  # a frame's median brightness (0-255) is pulled into this band
LOW_CONTRAST = 180.0  # spread between the 1st and 99th percentile below which a frame looks washed out


def frame_luma(rgb: np.ndarray) -> float:
    """Median brightness of a frame, 0-255."""
    return float(np.median(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)))


def exposure_gains(lumas: list[float]) -> list[float]:
    """One gain per frame so every frame ends up with a similar brightness.

    Frames are pulled toward the median of the clip (so a clip that drifts dark/bright
    as the phone's auto-exposure hunts becomes even), and the whole clip is nudged into
    TARGET_LUMA if it is very dark or very bright.
    """
    target = float(np.clip(np.median(lumas), *TARGET_LUMA))
    return [float(np.clip(target / max(l, 1.0), *GAIN_LIMITS)) for l in lumas]


def normalize_frame(rgb: np.ndarray, gain: float, stretch: float = 0.5) -> np.ndarray:
    """Apply a brightness gain, then gently stretch contrast if the frame looks washed out."""
    out = rgb.astype(np.float32) * gain
    gray = out.mean(axis=2)
    lo, hi = np.percentile(gray, [1, 99])
    if hi - lo < LOW_CONTRAST and hi > lo:
        # Linear stretch to the full range, blended in at `stretch` strength.
        full = (out - lo) * (255.0 / (hi - lo))
        out = out * (1 - stretch) + full * stretch
    return np.clip(out, 0, 255).astype(np.uint8)


def dominant_colors(rgb: np.ndarray, k: int = 3, max_points: int = 20000) -> list[dict]:
    """Most common colours in a set of points, biggest first: [{"hex": "#aabbcc", "share": 0.62}, ...].

    Plain k-means in Lab space (distances there match what the eye sees).
    """
    rgb = np.asarray(rgb, np.uint8).reshape(-1, 3)
    if len(rgb) < 30:
        return []
    if len(rgb) > max_points:
        rgb = rgb[np.random.default_rng(0).choice(len(rgb), max_points, replace=False)]
    lab = cv2.cvtColor(rgb.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    k = min(k, len(np.unique(rgb, axis=0)))
    cv2.setRNGSeed(0)
    _, labels, _ = cv2.kmeans(lab, k, None,  # type: ignore[call-overload]
                               (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5),
                              3, cv2.KMEANS_PP_CENTERS)
    labels = labels.ravel()
    out = []
    for c in range(k):
        m = labels == c
        if not m.any():
            continue
        mean = rgb[m].mean(axis=0).round().astype(int)
        out.append({"hex": "#{:02x}{:02x}{:02x}".format(*mean), "share": round(float(m.mean()), 3)})
    return sorted(out, key=lambda d: -d["share"])
