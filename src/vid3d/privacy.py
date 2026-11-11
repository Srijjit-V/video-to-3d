"""Delete the private by-products of a run: the frames are photos of the user's room."""

from __future__ import annotations

import shutil
from pathlib import Path

PRIVATE_DIRS = ("frames", "work")


def clean_intermediates(out: Path) -> None:
    for name in PRIVATE_DIRS:
        shutil.rmtree(out / name, ignore_errors=True)
