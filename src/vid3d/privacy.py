"""Delete the private by-products of a run: the frames are photos of the user's room."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

PRIVATE_DIRS = ("frames", "work")


def existing_private_dirs(out: Path) -> set[str]:
    """Names that already exist before a run starts: they are the user's, not ours to delete."""
    return {n for n in PRIVATE_DIRS if (out / n).exists() or (out / n).is_symlink()}


def clean_intermediates(out: Path, skip: Iterable[str] = ()) -> None:
    """Remove frames/ and work/ inside `out`, only real folders directly inside it, never symlinks."""
    root = out.resolve()
    for name in PRIVATE_DIRS:
        p = out / name
        if name in set(skip) or p.is_symlink() or not p.is_dir() or p.resolve().parent != root:
            continue
        shutil.rmtree(p, ignore_errors=True)
