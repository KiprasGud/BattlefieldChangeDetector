"""PERSON 2: call Gemini with both images + prompt, JSON-schema output, retries, validate."""
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
from .prompts import build_prompt

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_SIDE = 1536
RETRY_DELAYS = (1, 3)  # seconds between attempts -> 3 attempts total


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


def encode_jpeg(img: np.ndarray) -> bytes:
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("Could not encode image")
    return buf.tobytes()


def _make_client():
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


def analyze_with_gemini(img_a, aligned_b, criteria: str, lang: str = "en", client=None) -> AnalysisResult:
    from google.genai import types

    client = client or _make_client()
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    contents = [
        "Image A (past):",
        types.Part.from_bytes(data=encode_jpeg(img_a), mime_type="image/jpeg"),
        "Image B (present, aligned to Image A):",
        types.Part.from_bytes(data=encode_jpeg(aligned_b), mime_type="image/jpeg"),
        "Compare the images according to the analysis criteria and return the JSON report.",
    ]
    config = types.GenerateContentConfig(
        system_instruction=build_prompt(criteria, lang),
        response_mime_type="application/json",
        response_schema=LLMAnalysis,
        temperature=0.2,
    )

    last_error: Optional[Exception] = None
    for attempt, delay in enumerate((*RETRY_DELAYS, None), 1):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return to_result(_parse(response))
        except Exception as e:  # API, network or JSON errors: retry
            last_error = e
            log.warning("Gemini attempt %d failed: %s", attempt, e)
            if delay is not None:
                time.sleep(delay)
    raise RuntimeError(f"Gemini analysis failed: {last_error}")
