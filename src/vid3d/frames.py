"""Stage 1: pull a set of sharp, evenly spaced frames out of a video."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def sharpness(img: np.ndarray) -> float:
    """Variance of the Laplacian: higher means less motion blur."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def resize_max_side(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s >= 1:
        return img
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


def extract_frames(video_path: Path, out_dir: Path, target: int = 80, max_side: int = 1024) -> list[Path]:
    """Split the video into `target` equal windows and keep the sharpest frame of each."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    window = max(1, total // target) if total > 0 else 5

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()

    saved: list[Path] = []
    best, best_score, idx = None, -1.0, 0

    def flush():
        nonlocal best, best_score
        if best is not None:
            p = out_dir / f"frame_{len(saved):04d}.jpg"
            cv2.imwrite(str(p), best, [cv2.IMWRITE_JPEG_QUALITY, 95])
            saved.append(p)
        best, best_score = None, -1.0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = resize_max_side(frame, max_side)
        score = sharpness(frame)
        if score > best_score:
            best, best_score = frame, score
        idx += 1
        if idx % window == 0:
            flush()
    flush()
    cap.release()

    if len(saved) < 10:
        raise RuntimeError(f"Only {len(saved)} frames extracted; need a longer video.")
    return saved
