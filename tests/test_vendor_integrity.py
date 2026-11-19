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


def test_every_vendored_file_is_tracked_by_git_and_not_ignored():
    """A .gitignore rule such as `dist/` once silently left colmap-wasm's JavaScript out of the repository: it worked on one machine and
    broke on CI and on the deployed site. Every file a HASHES.json lists, and every file on disk under viewer/vendor, must be committed."""
    import json
    import subprocess

    vendor = ROOT / "viewer" / "vendor"
    on_disk = sorted(str(p.relative_to(ROOT)) for p in vendor.rglob("*") if p.is_file())
    assert on_disk
    tracked = set(subprocess.run(["git", "ls-files", "viewer/vendor"], cwd=ROOT, capture_output=True, text=True).stdout.split())
    ignored = subprocess.run(["git", "check-ignore", *on_disk], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert ignored == [], f"ignored by git, so never committed: {ignored}"
    assert [f for f in on_disk if f not in tracked] == [], "present on disk but not tracked (git add them)"
    for hashes in vendor.glob("*/HASHES.json"):
        for name in json.loads(hashes.read_text()):
            f = hashes.parent / name
            if f.exists():  # CDN-loaded files are recorded but intentionally not on disk
                assert str(f.relative_to(ROOT)) in tracked, f"{f} is listed in {hashes.name} but not tracked"


def test_the_vendored_colmap_package_is_complete_every_relative_import_and_asset_resolves():
    """The in-browser solve cannot be run on CI (no real GPU), so check the layout it depends on without a browser."""
    import re

    base = ROOT / "viewer" / "vendor" / "colmap-wasm"
    assert (base / "wasm" / "colmap.wasm").stat().st_size > 5_000_000
    for js in list((base / "dist").glob("*.js")) + [base / "wasm" / "colmap.mjs"]:
        for spec in re.findall(r"""(?:from\s*|import\s*\(\s*|new URL\(\s*)["'](\.{1,2}/[^"']+)["']""", js.read_text()):
            assert (js.parent / spec).resolve().exists(), f"{js.name} imports {spec}, which is missing"
    index = (ROOT / "viewer" / "js" / "colmap.js").read_text()
    assert "../vendor/colmap-wasm/dist/index.js" in index and (base / "dist" / "index.js").exists()
