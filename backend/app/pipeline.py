"""PERSON 3: orchestrates align -> diff/heatmap -> analyze -> annotate."""
import inspect
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

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


def run(
    bytes_a: bytes,
    bytes_b: bytes,
    criteria: str,
    lang: str = "en",
    draw_grid: bool = False,
    job_id: Optional[str] = None,
    stage_callback: Optional[Callable[[str, Optional[dict[str, float]]], None]] = None,
) -> AnalyzeResponse:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    warnings: list[str] = []

    if not job_id:
        job_id = uuid.uuid4().hex[:12]

    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    img_a = decode(bytes_a, "image_a")
    img_b = decode(bytes_b, "image_b")
    cv2.imwrite(str(job_dir / "image_a.jpg"), img_a)

    # Stage 1: Aligning
    if stage_callback:
        stage_callback("aligning", timings)
    t0 = time.perf_counter()
    aligned = align(img_a, img_b)
    timings["align"] = round(time.perf_counter() - t0, 3)

    method = getattr(aligned, "method", "none")
    if not aligned.ok:
        warnings.append(f"Alignment degraded: low quality score ({aligned.quality:.2f}).")
    if method == "ecc":
        warnings.append("Fallback ECC alignment applied due to insufficient feature matches.")
    elif method == "none":
        warnings.append("No perspective warp was applied.")

    images = {
        "image_a_url": f"/api/files/{job_id}/image_a.jpg",
        "aligned_b_url": f"/api/files/{job_id}/aligned_b.jpg",
    }
    cv2.imwrite(str(job_dir / "aligned_b.jpg"), aligned.aligned_b)

    # Stage 2: Heatmap
    if stage_callback:
        stage_callback("heatmap", timings)
    t0 = time.perf_counter()
    hints = None
    try:
        from .diff.heatmap import candidate_boxes, change_heatmap
        valid_mask = getattr(aligned, "valid_mask", None)
        heat_map = change_heatmap(img_a, aligned.aligned_b, valid_mask)
        hints = candidate_boxes(heat_map)
        heat_uint8 = (np.clip(heat_map, 0, 1) * 255).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_uint8, cv2.COLORMAP_JET)
        cv2.imwrite(str(job_dir / "heatmap.jpg"), heat_color)
        images["heatmap_url"] = f"/api/files/{job_id}/heatmap.jpg"
    except (ImportError, Exception):
        pass
    timings["heatmap"] = round(time.perf_counter() - t0, 3)

    # Stage 3: AI Analysis (with automatic offline fallback)
    if stage_callback:
        stage_callback("ai", timings)
    t0 = time.perf_counter()
    offline = False
    try:
        sig = inspect.signature(analyze)
        if "hints" in sig.parameters and hints is not None:
            result = analyze(img_a, aligned.aligned_b, criteria, lang, hints=hints)
        else:
            result = analyze(img_a, aligned.aligned_b, criteria, lang)
    except Exception as e:
        # Automatic offline fallback: switch to mock fixture when Gemini fails
        try:
            from .analysis.mock import analyze_mock
            result = analyze_mock(img_a, aligned.aligned_b, criteria)
            offline = True
            warnings.append(f"OFFLINE MODE: Gemini API unavailable ({type(e).__name__}). Using fixture data.")
        except Exception as fallback_err:
            raise RuntimeError(f"Both Gemini and mock fallback failed: {fallback_err}") from e
    timings["ai"] = round(time.perf_counter() - t0, 3)


    # Stage 4: Render
    if stage_callback:
        stage_callback("render", timings)
    t0 = time.perf_counter()
    annotated = annotate(aligned.aligned_b, result, draw_grid=draw_grid)
    cv2.imwrite(str(job_dir / "annotated.jpg"), annotated)
    images["annotated_url"] = f"/api/files/{job_id}/annotated.jpg"
    timings["render"] = round(time.perf_counter() - t0, 3)

    timings["total"] = round(time.perf_counter() - t_start, 3)
    if stage_callback:
        stage_callback("done", timings)

    return AnalyzeResponse(
        job_id=job_id,
        result=result,
        align_quality=aligned.quality,
        align_ok=aligned.ok,
        images=images,
        timings=timings,
        warnings=warnings,
    )
