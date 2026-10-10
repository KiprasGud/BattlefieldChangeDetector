"""PERSON 2: call Gemini with both images + prompt, JSON-schema output, retries, verification pass."""
import json
import logging
import os
import time
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel

from ..contracts import AnalysisResult
from .postprocess import to_result
from .prompts import build_prompt, build_verify_prompt

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_SIDE = 1536
RETRY_DELAYS = (1, 3)  # seconds between attempts -> 3 attempts total
MAX_VERIFY = 10  # verify at most this many detections (one call)
CROP_PAD = 0.15  # context around each box in verification crops, relative to box size
CROP_SIDE = 384


# LLM-facing schema: no sector / report_date, those are computed in postprocess.
class LLMChange(BaseModel):
    type: str
    description: str
    location_text: str
    confidence: str
    box: list[int]


class LLMAnalysis(BaseModel):
    summary: str
    changes: list[LLMChange]
    recommendation: str


class Verdict(BaseModel):
    index: int
    real: bool
    matches_criteria: bool
    reason: str


class LLMVerification(BaseModel):
    verdicts: list[Verdict]


def model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def verify_enabled() -> bool:
    return os.getenv("ANALYSIS_VERIFY", "1") == "1"


def encode_jpeg(img: np.ndarray, max_side: int = MAX_SIDE) -> bytes:
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("Could not encode image")
    return buf.tobytes()


def crop_box(img: np.ndarray, box: list[int], pad: float = CROP_PAD) -> np.ndarray:
    """Crop a 0-1000 box (plus padding) from img in pixels."""
    h, w = img.shape[:2]
    ymin, xmin, ymax, xmax = box
    py, px = (ymax - ymin) * pad, (xmax - xmin) * pad
    y0 = max(0, int((ymin - py) / 1000 * h))
    x0 = max(0, int((xmin - px) / 1000 * w))
    y1 = min(h, max(int((ymax + py) / 1000 * h), y0 + 1))
    x1 = min(w, max(int((xmax + px) / 1000 * w), x0 + 1))
    return img[y0:y1, x0:x1]


def make_client():
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=60_000),
    )


def _parse(response) -> dict:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, BaseModel):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed
    return json.loads(response.text)


def _generate(client, contents, config) -> dict:
    """One Gemini call with retries. Returns parsed JSON, raises RuntimeError after the last attempt."""
    last_error: Optional[Exception] = None
    for attempt, delay in enumerate((*RETRY_DELAYS, None), 1):
        try:
            response = client.models.generate_content(model=model_name(), contents=contents, config=config)
            return _parse(response)
        except Exception as e:  # API, network or JSON errors: retry
            last_error = e
            log.warning("Gemini attempt %d failed: %s", attempt, e)
            if delay is not None:
                time.sleep(delay)
    raise RuntimeError(f"Gemini analysis failed: {last_error}")


def _image_part(img: np.ndarray, max_side: int = MAX_SIDE):
    from google.genai import types

    return types.Part.from_bytes(data=encode_jpeg(img, max_side), mime_type="image/jpeg")


def verify_changes(client, img_a, aligned_b, criteria: str, result: AnalysisResult) -> AnalysisResult:
    """Second pass: show crops of every detection and drop the ones the model rejects.
    Any failure keeps the detections unchanged (verification must never lose a result)."""
    from google.genai import types

    candidates = result.changes[:MAX_VERIFY]
    if not candidates:
        return result
    contents = []
    for i, c in enumerate(candidates, 1):
        contents += [
            f"Candidate {i} ({c.type}): Image A crop:",
            _image_part(crop_box(img_a, c.box), CROP_SIDE),
            f"Candidate {i}: Image B crop:",
            _image_part(crop_box(aligned_b, c.box), CROP_SIDE),
        ]
    contents.append("Return one verdict per candidate.")
    config = types.GenerateContentConfig(
        system_instruction=build_verify_prompt(criteria),
        response_mime_type="application/json",
        response_schema=LLMVerification,
        temperature=0.0,
    )
    try:
        verdicts = _generate(client, contents, config).get("verdicts") or []
    except RuntimeError as e:
        log.warning("Verification skipped: %s", e)
        return result

    rejected = {
        v["index"] - 1
        for v in verdicts
        if isinstance(v, dict) and isinstance(v.get("index"), int) and not (v.get("real") and v.get("matches_criteria"))
    }
    kept = [c for i, c in enumerate(candidates) if i not in rejected] + result.changes[MAX_VERIFY:]
    if rejected:
        log.info("Verification rejected %d of %d detections", len(rejected), len(candidates))
    return result.model_copy(update={"changes": kept})


def analyze_with_gemini(
    img_a,
    aligned_b,
    criteria: str,
    lang: str = "en",
    hints: Optional[list[list[int]]] = None,
    client=None,
    verify: Optional[bool] = None,
) -> AnalysisResult:
    from google.genai import types

    client = client or make_client()
    contents = [
        "Image A (past):",
        _image_part(img_a),
        "Image B (present, aligned to Image A):",
        _image_part(aligned_b),
        "Compare the images according to the analysis criteria and return the JSON report.",
    ]
    config = types.GenerateContentConfig(
        system_instruction=build_prompt(criteria, lang, hints),
        response_mime_type="application/json",
        response_schema=LLMAnalysis,
        temperature=0.2,
    )
    result = to_result(_generate(client, contents, config), image_b=aligned_b)
    if verify if verify is not None else verify_enabled():
        result = verify_changes(client, img_a, aligned_b, criteria, result)
    return result
