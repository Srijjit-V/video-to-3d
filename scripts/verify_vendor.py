"""Check (or refresh) the integrity hashes of the bundled three.js files.

    python scripts/verify_vendor.py            # exit 1 if any file differs from vendor/three/HASHES.json
    python scripts/verify_vendor.py --update   # after you deliberately replaced a file; review the diff
    python scripts/verify_vendor.py --official # also download three@0.160.0 from npm and compare the unmodified file

The hash of three.module.min.js was compared with the official npm package three@0.160.0 (see README.txt there).
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "viewer" / "vendor" / "three"
FILES = ["three.module.min.js", "addons/OrbitControls.js", "addons/CSS2DRenderer.js"]
HASHES = VENDOR / "HASHES.json"
TJS_VENDOR = ROOT / "viewer" / "vendor" / "transformers"
TJS_FILES = ["ort-wasm-simd-threaded.asyncify.mjs"]  # bundled
TJS_REMOTE = ["transformers.min.js", "ort-wasm-simd-threaded.asyncify.wasm"]  # loaded from jsDelivr at an exact version; hash recorded only
TJS_HASHES = TJS_VENDOR / "HASHES.json"
TJS_VERSION = "4.3.2"
ORT_VERSION = "1.31.0-dev.20260914-8d85527a0"
ORT_WASM = "ort-wasm-simd-threaded.asyncify.wasm"  # loaded from a CDN at run time; its hash is recorded, not bundled


def sri(path: Path) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(path.read_bytes()).digest()).decode()


def current() -> dict[str, str]:
    return {f: sri(VENDOR / f) for f in FILES}


def tjs_current() -> dict[str, str]:
    h = {f: sri(TJS_VENDOR / f) for f in TJS_FILES}
    recorded = json.loads(TJS_HASHES.read_text()) if TJS_HASHES.exists() else {}
    for f in TJS_REMOTE:
        if f in recorded:
            h[f] = recorded[f]  # not on disk; kept as recorded
    return h


def main(argv: list[str]) -> int:
    if "--update" in argv:
        HASHES.write_text(json.dumps(current(), indent=2) + "\n")
        TJS_HASHES.write_text(json.dumps(tjs_current(), indent=2) + "\n")
        print("updated", HASHES, TJS_HASHES)
        return 0
    expected, actual = json.loads(HASHES.read_text()), current()
    bad = [f for f in FILES if expected.get(f) != actual[f]]
    for f in bad:
        print(f"MISMATCH {f}: expected {expected.get(f)}, got {actual[f]}")
    t_exp, t_act = json.loads(TJS_HASHES.read_text()), tjs_current()
    for f in TJS_FILES:
        if t_exp.get(f) != t_act[f]:
            print(f"MISMATCH transformers/{f}: expected {t_exp.get(f)}, got {t_act[f]}")
            bad.append(f)
    if "--official" in argv:
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["npm", "pack", "three@0.160.0", "--silent"], cwd=d, check=True, capture_output=True)
            subprocess.run(["tar", "-xzf", "three-0.160.0.tgz", "package/build/three.module.min.js"], cwd=d, check=True)
            if sri(Path(d) / "package/build/three.module.min.js") != actual["three.module.min.js"]:
                print("MISMATCH three.module.min.js differs from the official npm package")
                bad.append("official")
    if "--official" in argv:
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["npm", "pack", f"@huggingface/transformers@{TJS_VERSION}", "--silent"], cwd=d, check=True, capture_output=True)
            subprocess.run(["tar", "-xzf", f"huggingface-transformers-{TJS_VERSION}.tgz"], cwd=d, check=True)
            subprocess.run(["npm", "pack", f"onnxruntime-web@{ORT_VERSION}", "--silent"], cwd=d, check=True, capture_output=True)
            Path(d, "ort").mkdir()
            subprocess.run(["tar", "-xzf", f"onnxruntime-web-{ORT_VERSION}.tgz", "-C", "ort"], cwd=d, check=True)
            for f in TJS_FILES:
                src = Path(d) / "ort/package" / "dist" / f  # the loader ships in onnxruntime-web
                if sri(src) != t_act[f]:
                    print(f"MISMATCH transformers/{f} differs from the official npm package")
                    bad.append("official-" + f)
            if sri(Path(d) / "ort" / "package" / "dist" / ORT_WASM) != t_act[ORT_WASM]:
                print("MISMATCH the onnxruntime-web wasm differs from the recorded hash")
                bad.append("official-wasm")
            if sri(Path(d) / "package" / "dist" / "transformers.min.js") != t_act["transformers.min.js"]:
                print("MISMATCH transformers.min.js (loaded from the CDN) differs from the recorded hash")
                bad.append("official-transformers")
    print("vendor files ok" if not bad else f"{len(bad)} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
