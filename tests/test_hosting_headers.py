"""The security headers vercel.json sends (the Chrome tests run under these same headers)."""

import json
from pathlib import Path

HEADERS = {h["key"]: h["value"] for r in json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())["headers"]
           if r["source"] == "/(.*)" for h in r["headers"]}


def test_powerful_browser_features_are_switched_off():
    pp = HEADERS["Permissions-Policy"]
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in pp, feature


def test_csp_has_no_unsafe_script_sources_and_no_wildcard_script_host():
    csp = {d.split()[0]: d.split()[1:] for d in HEADERS["Content-Security-Policy"].split(";") if d.strip()}
    assert "'unsafe-inline'" not in csp["script-src"] and "'unsafe-eval'" not in csp["script-src"]
    assert not any(s.startswith("http") or s == "*" for s in csp["script-src"]), csp["script-src"]
    assert csp["default-src"] == ["'none'"] and csp["frame-ancestors"] == ["'none'"]


def test_framing_and_sniffing_are_refused():
    assert HEADERS["X-Frame-Options"] == "DENY" and HEADERS["X-Content-Type-Options"] == "nosniff"


def test_every_github_action_is_pinned_to_a_commit_sha():
    """A tag like @v4 can be moved; a commit SHA cannot. This keeps a compromised tag from running in CI."""
    import re

    wf = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    uses = [(f.name, m) for f in wf.glob("*.yml") for m in re.findall(r"uses:\s*(\S+)", f.read_text())]
    assert uses
    for name, ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{name}: {ref} is not pinned to a 40-character commit SHA"
