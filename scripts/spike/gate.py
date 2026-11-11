"""Phase 0 gate: do colmap-wasm's poses give the right room size when fed to the rest of the Python pipeline?

Run after colmap_spike.py: .venv/bin/python scripts/spike/gate.py
"""

import json
import shutil
import sys
from pathlib import Path

from vid3d.pipeline import process

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / "_work"


def main():
    r = json.loads((WORK / (sys.argv[1] if len(sys.argv) > 1 else "sfm_wasm.json")).read_text())
    cam = r["camera"]
    payload = {
        "version": 1,
        "camera": {"width": cam["width"], "height": cam["height"], "focal": cam["focal"], "cx": cam["cx"], "cy": cam["cy"], "k1": 0.0},
        "frames_total": r["total"], "reprojection_error_px": 0.0,
        "frames": [{"name": f["name"], "R": f["R"], "t": f["t"], "obs": f["obs"]} for f in r["frames"] if f["registered"]],
    }
    (WORK / "payload.json").write_text(json.dumps(payload))
    truth = json.loads((ROOT / "samples" / "synthetic_room.truth.json").read_text())
    for label, kw in (("true camera height", {"camera_height": truth["camera_height_m"]}), ("default 1.45 m", {})):
        out = WORK / "gate_run"
        shutil.rmtree(out, ignore_errors=True)
        s = process(ROOT / "samples" / "synthetic_room.mp4", out, sfm_payload=WORK / "payload.json", **kw)
        room = s["room"]
        dims = sorted([room["length_m"], room["width_m"]])
        t = sorted([truth["length_m"], truth["width_m"]])
        err = [round(100 * (a - b) / b, 1) for a, b in zip(dims, t, strict=True)]
        area_err = round(100 * (room["area_m2"] - truth["area_m2"]) / truth["area_m2"], 1)
        rg = s["uncertainty"]["ranges"]["area_m2"]
        print(f"{label}: {dims[0]} x {dims[1]} m, error % {err}, area {room['area_m2']} ({area_err}%), "
              f"range {rg}, contains truth: {rg[0] <= truth['area_m2'] and (rg[1] is None or truth['area_m2'] <= rg[1])}, confidence {s['confidence']['label']}")


if __name__ == "__main__":
    main()
