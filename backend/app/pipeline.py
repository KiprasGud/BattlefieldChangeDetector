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


def decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    return img


def run(bytes_a: bytes, bytes_b: bytes, criteria: str, lang: str = "en") -> AnalyzeResponse:
    img_a, img_b = decode(bytes_a), decode(bytes_b)
    aligned = align(img_a, img_b)
    result = analyze(img_a, aligned.aligned_b, criteria, lang)
    annotated = annotate(aligned.aligned_b, result)

    job_id = uuid.uuid4().hex[:12]
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(job_dir / "aligned_b.jpg"), aligned.aligned_b)
    cv2.imwrite(str(job_dir / "annotated.jpg"), annotated)
    return AnalyzeResponse(
        job_id=job_id,
        result=result,
        align_quality=aligned.quality,
        align_ok=aligned.ok,
        images={
            "aligned_b_url": f"/api/files/{job_id}/aligned_b.jpg",
            "annotated_url": f"/api/files/{job_id}/annotated.jpg",
        },
    )
