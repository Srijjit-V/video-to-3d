import numpy as np
import pytest


def box_room(L=5.0, W=4.0, H=2.6, step=0.05, seed=0):
    """Points on the floor, walls and ceiling of an axis-aligned room (y up)."""
    rng = np.random.default_rng(seed)
    xs, zs, ys = np.arange(0, L, step), np.arange(0, W, step), np.arange(0, H, step)
    X, Z = np.meshgrid(xs, zs)
    floor = np.c_[X.ravel(), np.zeros(X.size), Z.ravel()]
    ceil = np.c_[X.ravel(), np.full(X.size, H), Z.ravel()]
    walls = []
    for x in (0.0, L):
        Y, Zw = np.meshgrid(ys, zs)
        walls.append(np.c_[np.full(Y.size, x), Y.ravel(), Zw.ravel()])
    for z in (0.0, W):
        Xw, Y = np.meshgrid(xs, ys)
        walls.append(np.c_[Xw.ravel(), Y.ravel(), np.full(Y.size, z)])
    pts = np.concatenate([floor, ceil, *walls])
    return pts + rng.normal(0, 0.005, pts.shape)


@pytest.fixture
def room():
    return box_room()
