"""Cross-flight frame matching: pairs come from content, never from timestamps or frame order."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.video import describe, footprint_overlap, match_flights
from app.video import match as match_mod

SAMPLES = Path(__file__).resolve().parents[2] / "shared" / "sample_data"


@pytest.fixture(scope="module")
def flight_features(flights):
    a, b = flights.flight_a(), flights.flight_b()
    return a, b, [describe(f) for f, _ in a], [describe(f) for f, _ in b]


def test_flights_pair_by_content_not_time(flight_features, flights):
    a, b, fa, fb = flight_features
    assert len(fa) * len(fb) > match_mod.EXHAUSTIVE_MAX  # VLAD retrieval path, not brute force
    pairs = match_flights(fa, fb)
    assert len(pairs) >= 3
    for p in pairs:
        assert flights.overlap(a[p.a][1], b[p.b][1]) >= 0.5  # same ground per the true footprints
        assert abs(p.overlap - flights.overlap(a[p.a][1], b[p.b][1])) < 0.1
        assert 0.0 < p.ssim <= 1.0
    # B flew the opposite way: later A frames match earlier B frames
    assert [p.b for p in pairs] == sorted((p.b for p in pairs), reverse=True)
    # curated: the chosen A frames do not repeat each other's ground
    for i, p in enumerate(pairs):
        for q in pairs[i + 1:]:
            assert flights.overlap(a[p.a][1], a[q.a][1]) < 0.5


def test_max_pairs_caps_the_list(flight_features):
    _, _, fa, fb = flight_features
    assert len(match_flights(fa, fb, max_pairs=2)) == 2


def test_unrelated_flight_gives_no_pairs(flight_features):
    _, _, fa, _ = flight_features
    rng = np.random.default_rng(3)
    noise = [describe(cv2.GaussianBlur(rng.integers(0, 255, (360, 480, 3), dtype=np.uint8), (5, 5), 0))
             for _ in range(8)]
    assert match_flights(fa, noise) == []


def test_still_images_are_matched_exhaustively():
    a = cv2.imread(str(SAMPLES / "pair01" / "a.jpg"))
    b = cv2.flip(cv2.imread(str(SAMPLES / "pair01" / "b.jpg")), 1)  # mirrored still
    assert match_flights([describe(a)], [describe(b)]) == []  # video mode never tries mirrors
    pairs = match_flights([describe(a)], [describe(b)], mirror=True)
    assert len(pairs) == 1 and pairs[0].overlap > 0.95


def test_footprint_overlap():
    shape = (100, 200)
    assert footprint_overlap(np.eye(3), shape, shape) == pytest.approx(1.0)
    shift = np.array([[1, 0, 100], [0, 1, 0], [0, 0, 1.0]])
    assert footprint_overlap(shift, shape, shape) == pytest.approx(0.5)
    inside = np.array([[0.25, 0, 50], [0, 0.25, 25], [0, 0, 1.0]])  # a close-up lying inside the other view
    assert footprint_overlap(inside, shape, shape) == pytest.approx(1.0)
