"""Delete the private by-products of a run: the frames are photos of the user's room."""

from __future__ import annotations

import shutil
from pathlib import Path

PRIVATE_DIRS = ("frames", "work")


def check_private_dirs(out: Path, keep_intermediate: bool) -> None:
    """Refuse to start when a run could write through a link or mix with someone else's folders.

    A run owns out/frames and out/work. If they already exist we cannot tell what is in them, so we neither
    write into them (frames are deleted at the end) nor delete them: the user decides.
    """
    for name in PRIVATE_DIRS:
        p = out / name
        if p.is_symlink():
            raise RuntimeError(f"{p} is a link. Remove it or choose another --out folder.")
        if p.exists() and not keep_intermediate:
            raise RuntimeError(f"{p} already exists. Remove it, choose another --out folder, "
                               "or pass --keep-intermediate to reuse it and keep it afterwards.")


def clean_intermediates(out: Path) -> list[str]:
    """Remove frames/ and work/ inside `out`. Returns the names that are still there (so callers can warn)."""
    left = []
    root = out.resolve()
    for name in PRIVATE_DIRS:
        p = out / name
        if p.is_symlink() or (p.exists() and (not p.is_dir() or p.resolve().parent != root)):
            left.append(name)
            continue
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            if p.exists():
                left.append(name)
    return left
