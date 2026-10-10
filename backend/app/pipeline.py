"""PERSON 3: orchestrates align -> analyze -> annotate."""
import uuid
from pathlib import Path

import cv2
import numpy as np

from .alignment import align
from .analysis import analyze
from .contracts import AnalyzeResponse
from .render import annotate

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"


def decode(data: bytes, label: str = "image") -> np.ndarray:
    if not data:
        raise ValueError(f"Empty payload for {label}")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not decode {label}: invalid or corrupted image format")
    return img


def run(bytes_a: bytes, bytes_b: bytes, criteria: str, lang: str = "en", draw_grid: bool = False) -> AnalyzeResponse:
    img_a = decode(bytes_a, "image_a")
    img_b = decode(bytes_b, "image_b")
    aligned = align(img_a, img_b)
    result = analyze(img_a, aligned.aligned_b, criteria, lang)
    annotated = annotate(aligned.aligned_b, result, draw_grid=draw_grid)

    job_id = uuid.uuid4().hex[:12]
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(job_dir / "image_a.jpg"), img_a)
    cv2.imwrite(str(job_dir / "aligned_b.jpg"), aligned.aligned_b)
    cv2.imwrite(str(job_dir / "annotated.jpg"), annotated)
    return AnalyzeResponse(
        job_id=job_id,
        result=result,
        align_quality=aligned.quality,
        align_ok=aligned.ok,
        images={
            "image_a_url": f"/api/files/{job_id}/image_a.jpg",
            "aligned_b_url": f"/api/files/{job_id}/aligned_b.jpg",
            "annotated_url": f"/api/files/{job_id}/annotated.jpg",
        },
    )
