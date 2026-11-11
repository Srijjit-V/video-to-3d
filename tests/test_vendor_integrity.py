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
