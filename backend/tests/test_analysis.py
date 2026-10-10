import numpy as np

from app.analysis import analyze


def test_analyze_mock_matches_contract():
    img = np.zeros((10, 10, 3), np.uint8)
    r = analyze(img, img, "new tracks")
    assert r.changes and len(r.changes[0].box) == 4
