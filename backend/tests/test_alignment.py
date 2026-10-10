import numpy as np

from app.alignment import align


def test_align_returns_same_size():
    a = np.zeros((100, 120, 3), np.uint8)
    b = np.zeros((80, 90, 3), np.uint8)
    r = align(a, b)
    assert r.aligned_b.shape == a.shape
