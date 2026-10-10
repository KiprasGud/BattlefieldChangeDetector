"""PERSON 1 owns this file. Replace the stub with ORB/SIFT + RANSAC homography (+ ECC fallback)."""
import cv2
import numpy as np

from ..contracts import AlignResult


def align(img_a: np.ndarray, img_b: np.ndarray) -> AlignResult:
    """Warp img_b into img_a's frame. STUB: just resizes B to A's size."""
    h, w = img_a.shape[:2]
    resized = cv2.resize(img_b, (w, h))
    return AlignResult(aligned_b=resized, homography=None, quality=1.0, ok=True)
