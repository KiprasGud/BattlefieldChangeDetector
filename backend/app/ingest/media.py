"""Media kind and pixels from file content only: the extension, EXIF, file size and dates never count."""
import hashlib
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..alignment import IMREAD_PIXELS

# Leading bytes of the still-image formats OpenCV decodes. Anything else is handed to FFmpeg as video.
IMAGE_SIGNATURES = (
    b"\xff\xd8\xff",            # JPEG
    b"\x89PNG\r\n\x1a\n",       # PNG
    b"BM",                      # BMP
    b"II*\x00", b"MM\x00*",     # TIFF
)


def media_kind(path) -> str:
    """'image' or 'video', from the file header."""
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(IMAGE_SIGNATURES) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    return "video"


def load_still(path, max_side: Optional[int] = None) -> np.ndarray:
    """Decode an image from its bytes (Unicode paths work, EXIF orientation is ignored), shrunk to max_side."""
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), IMREAD_PIXELS)
    if img is None:
        raise ValueError(f"{Path(path).name}: not a decodable image")
    h, w = img.shape[:2]
    if max_side and max(h, w) > max_side:
        s = max_side / max(h, w)
        img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    return img


def content_hash(path, chunk: int = 1 << 20) -> str:
    """sha256 of the file bytes: identifies a source by content, so renamed or re-copied files are not redone."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()
