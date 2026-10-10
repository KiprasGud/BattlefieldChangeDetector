"""PERSON 3: draw red boxes + labels on the image."""
import cv2
import numpy as np

from ..contracts import AnalysisResult


def annotate(img: np.ndarray, result: AnalysisResult) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    for i, c in enumerate(result.changes, 1):
        ymin, xmin, ymax, xmax = c.box
        p1 = (int(xmin / 1000 * w), int(ymin / 1000 * h))
        p2 = (int(xmax / 1000 * w), int(ymax / 1000 * h))
        cv2.rectangle(out, p1, p2, (0, 0, 255), 3)
        cv2.putText(out, f"{i}", (p1[0], max(p1[1] - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    return out
