"""PERSON 3: orchestrates align -> diff/heatmap -> analyze -> annotate."""
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from .alignment import IMREAD_PIXELS, align, harmonize_resolution
from .analysis import analyze, use_mock
from .contracts import AnalyzeResponse
from .render import annotate

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"


def decode(data: bytes, label: str = "image") -> np.ndarray:
    if not data:
        raise ValueError(f"Empty payload for {label}")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), IMREAD_PIXELS)
    if img is None:
        raise ValueError(f"Could not decode {label}: invalid or corrupted image format")
    return img


def is_mirrored(homography) -> bool:
    return homography is not None and np.linalg.det(np.asarray(homography, np.float64)[:2, :2]) < 0


def run(
    bytes_a: bytes,
    bytes_b: bytes,
    criteria: str,
    lang: str = "en",
    draw_grid: bool = False,
    job_id: Optional[str] = None,
    stage_callback: Optional[Callable[[str, Optional[dict[str, float]]], None]] = None,
    meta: Optional[dict] = None,
) -> AnalyzeResponse:
    """meta: optional dict filled with extra job info not in the frozen contract (align_method)."""
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
    if meta is not None:
        meta["align_method"] = method
    if not aligned.ok:
        warnings.append(
            "Images could not be matched visually (too few common features). "
            "Image B is shown unaligned; detections are unreliable."
        )
    elif method == "ecc":
        warnings.append("Fallback ECC alignment applied due to insufficient feature matches.")
    if aligned.ok and is_mirrored(aligned.homography):
        warnings.append("Image B is mirrored relative to Image A; corrected during alignment.")

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
        try:
            # B coarser than A: blur A to B's resolution so edges don't light up (no-op otherwise).
            diff_a = harmonize_resolution(img_a, aligned.homography, img_b.shape)
        except Exception:
            diff_a = img_a
        heat_map = change_heatmap(diff_a, aligned.aligned_b, valid_mask)
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
    offline = use_mock()
    if offline:
        warnings.append("OFFLINE MODE: MOCK_LLM=1 or no GEMINI_API_KEY. Using fixture data.")
    try:
        result = analyze(img_a, aligned.aligned_b, criteria, lang, hints=hints, aligned=aligned.ok)
    except Exception as e:
        # Automatic offline fallback: switch to mock fixture when Gemini fails
        try:
            from .analysis.mock import analyze_mock
            result = analyze_mock(img_a, aligned.aligned_b, criteria, lang)
            offline = True
            reason = str(e)[:120] or type(e).__name__
            warnings.append(f"OFFLINE MODE: Gemini API unavailable ({reason}). Using fixture data.")
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
