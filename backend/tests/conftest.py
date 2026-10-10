import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["MOCK_LLM"] = "1"


def _scale(sx: float, sy: float) -> np.ndarray:
    # cv2.resize maps pixel centres: x' = sx * x + (sx - 1) / 2
    return np.array([[sx, 0, (sx - 1) / 2], [0, sy, (sy - 1) / 2], [0, 0, 1]])


def transform_image(img: np.ndarray, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """Visually modified copy of img and the exact 3x3 map from img's pixels to the copy's pixels."""
    h, w = img.shape[:2]
    if kind == "hflip":
        return cv2.flip(img, 1), np.array([[-1, 0, w - 1], [0, 1, 0], [0, 0, 1.0]])
    if kind == "vflip":
        return cv2.flip(img, 0), np.array([[1, 0, 0], [0, -1, h - 1], [0, 0, 1.0]])
    if kind == "transpose":
        return cv2.transpose(img), np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1.0]])
    if kind == "rot90":
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), np.array([[0, -1, h - 1], [1, 0, 0], [0, 0, 1.0]])
    if kind == "rot180":
        return cv2.rotate(img, cv2.ROTATE_180), np.array([[-1, 0, w - 1], [0, -1, h - 1], [0, 0, 1.0]])
    if kind.startswith("rot"):  # rot<degrees>, black corners
        m = cv2.getRotationMatrix2D((w / 2, h / 2), float(kind[3:]), 1.0)
        return cv2.warpAffine(img, m, (w, h)), np.vstack([m, [0, 0, 1]])
    if kind.startswith("scale"):  # scale<factor>
        s = float(kind[5:])
        size = (round(w * s), round(h * s))
        out = cv2.resize(img, size, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        return out, _scale(size[0] / w, size[1] / h)
    if kind == "stretch":  # aspect ratio change
        size = (round(w * 1.5), h)
        return cv2.resize(img, size, interpolation=cv2.INTER_CUBIC), _scale(size[0] / w, 1.0)
    if kind.startswith("crop"):  # crop<percent per side>
        f = int(kind[4:]) / 100
        dy, dx = int(h * f), int(w * f)
        return img[dy:h - dy, dx:w - dx], np.array([[1, 0, -dx], [0, 1, -dy], [0, 0, 1.0]])
    if kind == "bright":
        return cv2.convertScaleAbs(img, alpha=1.0, beta=30), np.eye(3)
    if kind == "brightblur":
        return cv2.convertScaleAbs(cv2.GaussianBlur(img, (5, 5), 0), alpha=1.2, beta=20), np.eye(3)
    if kind == "jpeg30":
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 30])
        return cv2.imdecode(buf, cv2.IMREAD_COLOR), np.eye(3)
    if kind == "combo":  # mirror + rotate 45 + crop 10% + downscale 0.6
        out, total = img, np.eye(3)
        for step in ("hflip", "rot45", "crop10", "scale0.6"):
            out, t = transform_image(out, step)
            total = t @ total
        return out, total
    raise ValueError(kind)


@pytest.fixture
def transform():
    return transform_image
