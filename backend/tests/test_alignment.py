import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import cv2
import numpy as np
import pytest
from pathlib import Path

from app.alignment import align, harmonize_resolution
from app.alignment.register import normalize_brightness
from app.diff.heatmap import candidate_boxes, change_heatmap

SAMPLES = Path(__file__).resolve().parents[2] / "shared" / "sample_data"


def create_synthetic_image():
    # Create a base image (A) with some features, make it a bit larger and feature-rich for SIFT
    img = np.zeros((400, 400, 3), np.uint8)
    for i in range(10):
        cv2.rectangle(img, (50 + i*20, 50 + i*20), (150 + i*20, 150 + i*20), (255 - i*10, 255 - i*20, i*25), -1)
    cv2.circle(img, (200, 200), 50, (0, 0, 255), -1)
    cv2.putText(img, "TEST ALIGNMENT", (60, 300), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    # Add noise for more keypoints
    noise = np.random.randint(0, 50, (400, 400, 3), dtype=np.uint8)
    img = cv2.add(img, noise)
    return img


def test_align_returns_same_size():
    a = np.zeros((100, 120, 3), np.uint8)
    b = np.zeros((80, 90, 3), np.uint8)
    r = align(a, b)
    assert r.aligned_b.shape == a.shape


def test_align_synthetic_shifted():
    img_a = create_synthetic_image()
    # Shift B slightly
    M = np.float32([[1, 0, 10], [0, 1, 10]])
    img_b = cv2.warpAffine(img_a, M, (400, 400))
    
    r = align(img_a, img_b)
    
    assert r.ok is True
    assert r.quality > 0.0
    assert r.homography is not None
    # We test for method attribute existence safely (no-op until M0 is fully merged in API)
    method = getattr(r, "method", None) or r.__dict__.get("method")
    assert method in ["sift", "ecc", "none"]


def test_brightness_normalization():
    img = np.zeros((100, 100, 3), np.uint8)
    cv2.rectangle(img, (0, 0), (50, 100), (50, 50, 50), -1)
    cv2.rectangle(img, (50, 0), (100, 100), (100, 100, 100), -1)
    norm = normalize_brightness(img)
    assert norm.shape == img.shape


def test_align_rotation_scaling_brightness():
    img_a = create_synthetic_image()
    
    # Scale 0.9, Rotate 10 deg
    center = (200, 200)
    M = cv2.getRotationMatrix2D(center, 10, 0.9)
    img_b = cv2.warpAffine(img_a, M, (400, 400))
    
    # Brightness shift
    img_b = cv2.convertScaleAbs(img_b, alpha=1.2, beta=30)
    
    r = align(img_a, img_b)
    assert r.ok is True


def test_align_perspective_warp():
    img_a = create_synthetic_image()
    
    pts1 = np.float32([[50, 50], [350, 50], [50, 350], [350, 350]])
    pts2 = np.float32([[50, 60], [350, 40], [60, 350], [340, 360]])
    M = cv2.getPerspectiveTransform(pts1, pts2)
    
    img_b = cv2.warpPerspective(img_a, M, (400, 400))
    
    r = align(img_a, img_b)
    assert r.ok is True


def test_degenerate_input():
    img_a = create_synthetic_image()
    # Blank image
    img_b = np.zeros((400, 400, 3), np.uint8)

    r = align(img_a, img_b)
    assert r.ok is False
    assert r.homography is None


# --- visual matching robustness (sample pairs: A and B share one frame, so B's transform is the truth) ---

def _sample(pair, name):
    return cv2.imread(str(SAMPLES / pair / f"{name}.jpg"))


def _max_error(H, T, a_shape, b2_shape):
    """Largest distance (A pixels) between where H puts points of the transformed B and where they belong."""
    h, w = a_shape[:2]
    ys, xs = np.mgrid[h * 0.1:h * 0.9:9j, w * 0.1:w * 0.9:9j]
    pts = np.vstack([xs.ravel(), ys.ravel(), np.ones(xs.size)])
    in_b2 = T @ pts
    in_b2 = in_b2[:2] / in_b2[2]
    hb, wb = b2_shape[:2]
    inside = (in_b2[0] >= 0) & (in_b2[0] <= wb - 1) & (in_b2[1] >= 0) & (in_b2[1] <= hb - 1)
    back = np.asarray(H) @ np.vstack([in_b2, np.ones(in_b2.shape[1])])
    back = back[:2] / back[2]
    return float(np.linalg.norm((back - pts[:2])[:, inside], axis=0).max())


ROBUSTNESS_CASES = [("pair01", k) for k in (
    "hflip", "vflip", "transpose", "rot90", "rot180", "rot30", "scale0.5", "scale0.35", "scale2.5",
    "stretch", "crop10", "crop20", "crop30", "combo", "brightblur", "jpeg30",
)] + [("pair02", k) for k in ("hflip", "rot90", "crop20", "scale0.5")]


@pytest.mark.parametrize("pair,kind", ROBUSTNESS_CASES)
def test_align_recovers_visual_transform(pair, kind, transform):
    a, b = _sample(pair, "a"), _sample(pair, "b")
    b2, T = transform(b, kind)
    r = align(a, b2)
    assert r.ok is True and r.method == "sift"
    assert r.aligned_b.shape == a.shape
    assert _max_error(r.homography, T, a.shape, b2.shape) <= 1.5
    mirrored = np.linalg.det(np.asarray(r.homography)[:2, :2]) < 0
    assert mirrored == (kind in ("hflip", "vflip", "transpose", "combo"))


def test_align_rejects_different_scene():
    r = align(_sample("pair01", "a"), _sample("pair02", "b"))
    assert r.ok is False and r.homography is None


def test_align_rejects_noise():
    noise = np.random.default_rng(1).integers(0, 255, (600, 800, 3), dtype=np.uint8)
    assert align(_sample("pair01", "a"), noise).ok is False


def test_already_aligned_pair_is_not_resampled():
    a, b = _sample("pair01", "a"), _sample("pair01", "b")
    r = align(a, b)
    assert r.ok and np.allclose(r.homography, np.eye(3))
    assert np.array_equal(r.aligned_b, b)


def test_ecc_fallback_needs_real_correlation(monkeypatch):
    from app.alignment import register
    monkeypatch.setattr(register, "estimate_homography", lambda *args, **kwargs: None)  # no feature solution
    a, b = _sample("pair01", "a"), _sample("pair01", "b")
    assert align(a, cv2.flip(b, 1)).ok is False  # used to report "aligned" at correlation 0.14
    r = align(a, b)
    assert r.ok and r.method == "ecc"


def test_harmonize_resolution_only_when_b_is_coarser():
    a = _sample("pair01", "a")
    assert harmonize_resolution(a, None, a.shape) is a
    assert harmonize_resolution(a, np.eye(3).tolist(), a.shape) is a
    out = harmonize_resolution(a, np.diag([2.0, 2.0, 1.0]).tolist(), (300, 400, 3))  # each B pixel covers 2x2 A pixels
    assert out.shape == a.shape

    def sharpness(img):
        return cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()

    assert sharpness(out) < sharpness(a)


def test_half_resolution_b_gives_clean_heatmap():
    a, b = _sample("pair01", "a"), _sample("pair01", "b")
    small = cv2.resize(b, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    r = align(a, small)
    heat = change_heatmap(harmonize_resolution(a, r.homography, small.shape), r.aligned_b, r.valid_mask)
    assert len(candidate_boxes(heat)) <= 3  # without harmonizing: 10 edge-noise candidates

