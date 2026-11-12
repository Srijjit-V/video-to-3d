"""Send the frames (never the video) to a camera-solve server and get the sfm payload back."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request  # noqa: S310 - the URL scheme is checked below
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from .sfm_payload import validate


def solve_remote(frames_dir: Path, server_url: str, fov: float, timeout: float = 1200.0) -> dict:
    u = urlparse(server_url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("The server address must start with http:// or https://")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # JPEGs do not compress further
        for f in sorted(frames_dir.glob("*.jpg")):
            z.write(f, f.name)
    req = urllib.request.Request(  # noqa: S310
        f"{server_url.rstrip('/')}/v1/sfm?fov={fov:g}", data=buf.getvalue(), method="POST",
        headers={"Content-Type": "application/zip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", "")
        except (ValueError, OSError):
            msg = ""
        raise RuntimeError(msg or f"The camera-solve server answered {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"Could not reach the camera-solve server: {e}") from e
    validate(payload)  # it came over the network: check before use
    return payload
