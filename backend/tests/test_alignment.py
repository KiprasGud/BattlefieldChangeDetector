import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import cv2
import numpy as np
import math

from app.alignment import align
from app.alignment.register import write_debug_overlay, normalize_brightness


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

