import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_vendor", ROOT / "scripts" / "verify_vendor.py")
vv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vv)


def test_bundled_three_js_matches_the_recorded_hashes():
    assert vv.main([]) == 0


def test_page_preloads_three_js_with_its_integrity_hash():
    html = (ROOT / "viewer" / "index.html").read_text()
    m = re.search(r'<link rel="modulepreload" href="vendor/three/three\.module\.min\.js" integrity="([^"]+)"', html)
    assert m, "index.html must preload three.js with an integrity attribute"
    assert m.group(1) == vv.current()["three.module.min.js"]


def test_bundled_demo_scenes_are_tracked_by_git_and_not_ignored():
    import subprocess

    files = [f"viewer/{d}/{f}" for d in ("sample", "sample-bad") for f in ("cloud.ply", "scene.json", "floorplan.png")]
    ignored = subprocess.run(["git", "check-ignore", *files], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert ignored == [], f".gitignore hides demo files: {ignored}"
    tracked = subprocess.run(["git", "ls-files", *files], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert sorted(tracked) == sorted(files)
    assert sum((ROOT / f).stat().st_size for f in files) < 5_000_000
