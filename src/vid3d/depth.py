"""Stage 3: AI depth per frame, locked to the camera solve so all frames agree.

Depth Anything V2 gives *relative* depth (good shape, unknown scale/offset per
frame). COLMAP gives a few hundred exact-but-sparse 3D points per frame. We fit
the AI output to those points, which turns it into consistent dense depth.
"""

from __future__ import annotations

import numpy as np

MODEL_NAME = "depth-anything/Depth-Anything-V2-Small-hf"


def pick_device():
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class DepthModel:
    def __init__(self, device: str | None = None):
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        self.device = device or pick_device()
        self.processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
        self.model = AutoModelForDepthEstimation.from_pretrained(MODEL_NAME).to(self.device).eval()

    def disparity(self, rgb: np.ndarray) -> np.ndarray:
        """Relative inverse depth (bigger = closer), same size as the input."""
        import torch

        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        with torch.no_grad():
            out = self.model(**inputs).predicted_depth  # (1, h, w)
        out = torch.nn.functional.interpolate(
            out[:, None], size=rgb.shape[:2], mode="bicubic", align_corners=False
        )[0, 0]
        return out.float().cpu().numpy()


def align_disparity(disp_samples: np.ndarray, z: np.ndarray, iters: int = 3):
    """Fit 1/z ≈ a*disp + b robustly. Returns (a, b, inlier_fraction) or None."""
    if len(z) < 20:
        return None
    target = 1.0 / z
    # Robust start (Theil-Sen): median slope over random pairs, so a few bad
    # matches can't drag the fit the way a plain least-squares start would.
    rng = np.random.default_rng(0)
    i, j = rng.integers(0, len(z), (2, 2000))
    dd = disp_samples[i] - disp_samples[j]
    ok = np.abs(dd) > 1e-9
    if ok.sum() < 10:
        return None
    a = float(np.median((target[i] - target[j])[ok] / dd[ok]))
    b = float(np.median(target - a * disp_samples))
    res = np.abs(a * disp_samples + b - target)
    keep = res < 3.0 * 1.4826 * (np.median(res) + 1e-12)
    for _ in range(iters):
        A = np.stack([disp_samples[keep], np.ones(keep.sum())], 1)
        (a, b), *_ = np.linalg.lstsq(A, target[keep], rcond=None)
        res = np.abs(a * disp_samples + b - target)
        mad = np.median(res[keep]) + 1e-12
        keep = res < 3.0 * 1.4826 * mad
        if keep.sum() < 15:
            return None
    if a <= 0:
        return None
    return float(a), float(b), float(keep.mean())


def metric_depth(disp: np.ndarray, a: float, b: float, z_min: float, z_max: float) -> np.ndarray:
    """Turn disparity into depth; NaN where the fit is unreliable or on depth edges."""
    inv = a * disp + b
    depth = np.full(disp.shape, np.nan, np.float32)
    ok = inv > 1e-6
    depth[ok] = 1.0 / inv[ok]
    depth[(depth < z_min) | (depth > z_max)] = np.nan

    # Drop "flying pixels" smeared across object edges.
    gy, gx = np.gradient(depth)
    rel = np.sqrt(gx**2 + gy**2) / depth
    depth[~(rel < 0.04)] = np.nan
    return depth
