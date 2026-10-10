"""PERSON 2: call Gemini with both images + prompt, JSON-schema output, retries, verification pass."""
import json
import logging
import os
import time
from typing import Literal, Optional

import cv2
import numpy as np
from pydantic import BaseModel, Field

from ..contracts import AnalysisResult, Category
from .postprocess import to_result
from .prompts import TYPE_RULE, build_prompt, build_verify_prompt

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash-lite"
THINKING_LEVELS = ("minimal", "low", "medium", "high")
MAX_SIDE = 1536
RETRY_DELAYS = (1, 3)  # seconds between attempts -> 3 attempts total
MAX_VERIFY = 20  # verify at most this many detections (one call)
CROP_PAD = 0.15  # context around each box in verification crops, relative to box size
CROP_SIDE = 384


class GeminiError(RuntimeError):
    """A Gemini call failed for good: non-retryable error, or every retry used up."""


# LLM-facing schema: no sector / report_date, those are computed in postprocess.
class LLMChange(BaseModel):
    type: str = Field(description=TYPE_RULE[0].upper() + TYPE_RULE[1:])
    category: Category
    description: str
    location_text: str
    confidence: Literal["high", "medium", "low"]
    box: list[int] = Field(description="[ymin, xmin, ymax, xmax] in Image B, normalized 0-1000")


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


def is_legacy_model(model: Optional[str] = None) -> bool:
    """Gemini 1.x/2.x take sampling params; 3.x ignores them (later generations reject them with HTTP 400)."""
    return (model or model_name()).startswith(("gemini-1", "gemini-2"))


def thinking_level() -> str:
    level = os.getenv("GEMINI_THINKING_LEVEL", "minimal").strip().lower()
    return level if level in THINKING_LEVELS else "minimal"


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


def _config(system_instruction: str, schema, legacy_temperature: float):
    from google.genai import types

    kwargs = {"system_instruction": system_instruction, "response_mime_type": "application/json", "response_schema": schema}
    if is_legacy_model():
        kwargs["temperature"] = legacy_temperature
    else:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level())
    return types.GenerateContentConfig(**kwargs)


def _parse(response) -> dict:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, BaseModel):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed
    return json.loads(response.text)


def _retryable(error: Exception) -> bool:
    """Rate limits, server errors, timeouts, network and JSON problems are worth retrying; other 4xx are not."""
    from google.genai import errors

    if isinstance(error, errors.APIError):
        return error.code in (408, 429) or (error.code or 0) >= 500
    return True


def _describe(error: Optional[Exception]) -> str:
    from google.genai import errors

    if isinstance(error, errors.APIError):
        return f"{error.code} {error.status}: {error.message}"[:200]
    return f"{type(error).__name__}: {error}"[:200]


def _generate(client, contents, config) -> dict:
    """One Gemini call with retries. Returns parsed JSON, raises GeminiError when it gives up."""
    last_error: Optional[Exception] = None
    for attempt, delay in enumerate((*RETRY_DELAYS, None), 1):
        try:
            response = client.models.generate_content(model=model_name(), contents=contents, config=config)
            return _parse(response)
        except Exception as e:  # API, network or JSON errors
            last_error = e
            log.warning("Gemini attempt %d failed: %s", attempt, e)
            if not _retryable(e):
                break
            if delay is not None:
                time.sleep(delay)
    raise GeminiError(f"Gemini analysis failed: {_describe(last_error)}") from last_error


def _image_part(img: np.ndarray, max_side: int = MAX_SIDE, detail: str = "HIGH"):
    """JPEG part built from pixels only (no metadata reaches the model); Gemini 3 gets a per-image token budget."""
    from google.genai import types

    data = encode_jpeg(img, max_side)
    if is_legacy_model():
        return types.Part.from_bytes(data=data, mime_type="image/jpeg")
    level = getattr(types.PartMediaResolutionLevel, f"MEDIA_RESOLUTION_{detail}")
    return types.Part.from_bytes(data=data, mime_type="image/jpeg", media_resolution=level)


def verify_changes(
    client, img_a: np.ndarray, aligned_b: np.ndarray, criteria: str, result: AnalysisResult
) -> AnalysisResult:
    """Second pass: show crops of every detection and drop the ones the model rejects.
    Any failure keeps the detections unchanged (verification must never lose a result)."""
    candidates = result.changes[:MAX_VERIFY]
    if not candidates:
        return result
    contents = []
    for i, c in enumerate(candidates, 1):
        contents += [
            f"Candidate {i} ({c.type}): Image A crop:",
            _image_part(crop_box(img_a, c.box), CROP_SIDE, "MEDIUM"),
            f"Candidate {i}: Image B crop:",
            _image_part(crop_box(aligned_b, c.box), CROP_SIDE, "MEDIUM"),
        ]
    contents.append("Return one verdict per candidate.")
    config = _config(build_verify_prompt(criteria), LLMVerification, legacy_temperature=0.0)
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
    img_a: np.ndarray,
    aligned_b: np.ndarray,
    criteria: str,
    lang: str = "en",
    hints: Optional[list[list[int]]] = None,
    client=None,
    verify: Optional[bool] = None,
    aligned: bool = True,
) -> AnalysisResult:
    client = client or make_client()
    contents = [
        "Image A (past):",
        _image_part(img_a),
        "Image B (present, aligned to Image A):" if aligned else "Image B (present, NOT aligned to Image A):",
        _image_part(aligned_b),
        "Compare the images according to the analysis criteria and return the JSON report.",
    ]
    config = _config(build_prompt(criteria, lang, hints, aligned), LLMAnalysis, legacy_temperature=0.2)
    result = to_result(_generate(client, contents, config), image_b=aligned_b)
    if verify if verify is not None else verify_enabled():
        result = verify_changes(client, img_a, aligned_b, criteria, result)
    return result
