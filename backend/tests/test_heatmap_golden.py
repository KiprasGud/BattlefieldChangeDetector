"""Guards the validated change heatmap: its output for the sample pairs was recorded before the batch pipeline
was added, and the batch path's input fix (fill_uncovered) must not alter full-coverage pairs."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.alignment import IMREAD_PIXELS, align
from app.analysis.tiling import iou
from app.pipeline import compute_heatmap

SAMPLES = Path(__file__).resolve().parents[2] / "shared" / "sample_data"

# candidate_boxes of the single-pair flow, recorded from main before any batch-pipeline change
GOLDEN = {
    "pair01": [[178, 622, 315, 886], [463, 322, 555, 391]],
    "pair02": [[711, 182, 773, 478], [743, 146, 755, 167]],
}


def _pair(name):
    return (cv2.imread(str(SAMPLES / name / "a.jpg"), IMREAD_PIXELS),
            cv2.imread(str(SAMPLES / name / "b.jpg"), IMREAD_PIXELS))


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_single_pair_heatmap_unchanged(name):
    a, b = _pair(name)
    _, boxes = compute_heatmap(a, b, align(a, b))
    assert boxes == GOLDEN[name]


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_fill_is_a_no_op_on_full_coverage(name):
    a, b = _pair(name)
    r = align(a, b)
    plain, _ = compute_heatmap(a, b, r)
    filled, _ = compute_heatmap(a, b, r, fill_uncovered=True)
    assert np.array_equal(plain, filled)


def test_fill_removes_border_bleed_on_partial_coverage():
    a, b = _pair("pair01")
    h, w = b.shape[:2]
    crop = b[int(h * 0.15):, int(w * 0.15):]  # B covers only the lower-right 85% of A
    r = align(a, crop)
    _, plain = compute_heatmap(a, crop, r)
    _, filled = compute_heatmap(a, crop, r, fill_uncovered=True)
    assert len(filled) < len(plain)
    for real in GOLDEN["pair01"]:  # both real changes survive
        assert max(iou(real, box) for box in filled) >= 0.8
