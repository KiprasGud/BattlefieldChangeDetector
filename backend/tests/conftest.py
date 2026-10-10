import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["MOCK_LLM"] = "1"
os.environ["WATCH_ENABLED"] = "0"

SAMPLES = Path(__file__).resolve().parents[2] / "shared" / "sample_data"


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


class Flights:
    """Synthetic drone flights over a 1600x600 mosaic of the sample pairs: world "a" = before, "b" = after.
    Flight A runs left to right at reference altitude; flight B runs the other way, 1.25x higher, camera turned
    15 degrees, at a different speed. Footprints are the frame corners in world pixels (ground truth)."""

    SIZE = (480, 360)

    @staticmethod
    def world(name: str) -> np.ndarray:
        return np.hstack([cv2.imread(str(SAMPLES / p / f"{name}.jpg")) for p in ("pair01", "pair02")])

    @classmethod
    def view(cls, world: np.ndarray, cx: float, cy: float, scale: float = 1.0, angle: float = 0.0):
        """Frame centred on world (cx, cy); one frame pixel spans `scale` world pixels."""
        w, h = cls.SIZE
        a = np.deg2rad(angle)
        rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) * scale
        t = np.array([cx, cy]) - rot @ np.array([w / 2, h / 2])
        frame = cv2.warpAffine(world, np.hstack([rot, t[:, None]]), (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
        footprint = (rot @ np.array([[0, w, w, 0], [0, 0, h, h]]) + t[:, None]).T.astype(np.float32)
        return frame, footprint

    @classmethod
    def flight_a(cls, frames: int = 12, world=None):
        world = cls.world("a") if world is None else world
        return [cls.view(world, cx, 300) for cx in np.linspace(260, 1340, frames)]

    @classmethod
    def flight_b(cls, frames: int = 8, world=None):
        world = cls.world("b") if world is None else world
        return [cls.view(world, cx, 300, 1.25, 15) for cx in np.linspace(1250, 350, frames)]

    @staticmethod
    def overlap(p: np.ndarray, q: np.ndarray) -> float:
        """Shared ground as a share of the smaller footprint."""
        inter, _ = cv2.intersectConvexConvex(p, q)
        return inter / min(cv2.contourArea(p), cv2.contourArea(q))

    @staticmethod
    def write_video(path: Path, frames, fps: float = 0.5) -> Path:
        """MJPG/AVI at `fps`: at 0.5 fps every frame is exactly one 2 s extraction step."""
        tmp = path.with_name(path.name + ".tmp.avi")  # OpenCV picks the container from the extension
        h, w = frames[0].shape[:2]
        writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
        for f in frames:
            writer.write(f)
        writer.release()
        tmp.replace(path)
        return path


@pytest.fixture(scope="session")
def flights():
    return Flights
