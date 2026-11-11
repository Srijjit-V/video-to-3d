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

VENDOR = Path(__file__).resolve().parents[1] / "viewer" / "vendor" / "three"
FILES = ["three.module.min.js", "addons/OrbitControls.js", "addons/CSS2DRenderer.js"]
HASHES = VENDOR / "HASHES.json"


def sri(path: Path) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(path.read_bytes()).digest()).decode()


def current() -> dict[str, str]:
    return {f: sri(VENDOR / f) for f in FILES}


def main(argv: list[str]) -> int:
    if "--update" in argv:
        HASHES.write_text(json.dumps(current(), indent=2) + "\n")
        print("updated", HASHES)
        return 0
    expected, actual = json.loads(HASHES.read_text()), current()
    bad = [f for f in FILES if expected.get(f) != actual[f]]
    for f in bad:
        print(f"MISMATCH {f}: expected {expected.get(f)}, got {actual[f]}")
    if "--official" in argv:
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["npm", "pack", "three@0.160.0", "--silent"], cwd=d, check=True, capture_output=True)
            subprocess.run(["tar", "-xzf", "three-0.160.0.tgz", "package/build/three.module.min.js"], cwd=d, check=True)
            if sri(Path(d) / "package/build/three.module.min.js") != actual["three.module.min.js"]:
                print("MISMATCH three.module.min.js differs from the official npm package")
                bad.append("official")
    print("vendor files ok" if not bad else f"{len(bad)} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
