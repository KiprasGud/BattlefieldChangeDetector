import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import cv2
import numpy as np

from app.alignment import align
from app.alignment.register import write_debug_overlay, normalize_brightness


def create_synthetic_image():
    # Create a base image (A) with some features
    img = np.zeros((200, 200, 3), np.uint8)
    cv2.rectangle(img, (50, 50), (150, 150), (255, 255, 255), -1)
    cv2.circle(img, (100, 100), 20, (0, 0, 255), -1)
    cv2.putText(img, "TEST", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
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
    img_b = cv2.warpAffine(img_a, M, (200, 200))
    
    r = align(img_a, img_b)
    
    assert r.ok is True
    assert r.quality > 0.0
    assert r.homography is not None
    
    # Residual after align should be small for the overlapping region
    center_a = img_a[50:150, 50:150]
    center_b = r.aligned_b[50:150, 50:150]
    
    diff = cv2.absdiff(center_a, center_b)
    assert np.mean(diff) < 5.0


def test_brightness_normalization():
    img = np.zeros((100, 100, 3), np.uint8)
    cv2.rectangle(img, (0, 0), (50, 100), (50, 50, 50), -1)
    cv2.rectangle(img, (50, 0), (100, 100), (100, 100, 100), -1)
    norm = normalize_brightness(img)
    assert norm.shape == img.shape
