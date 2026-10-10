"""Validate and normalize raw LLM output into the frozen AnalysisResult contract."""
from datetime import date
from typing import Optional

import numpy as np

from ..contracts import CATEGORY_LABELS, AnalysisResult, Change

MIN_SIDE = 5  # boxes thinner than this (in 0-1000 units) are dropped
BLACK_LEVEL = 3  # pixel max channel <= this counts as warp border
MAX_UNCOVERED = 0.6  # drop boxes with more than 60% of their area in the black border

CONFIDENCE_MAP = {
    "high": "high", "medium": "medium", "low": "low",
    "aukštas": "high", "aukstas": "high",
    "vidutinis": "medium",
    "žemas": "low", "zemas": "low",
}


def clean_box(box) -> Optional[list[int]]:
    """Clamp to 0-1000, fix swapped corners; None if malformed or degenerate."""
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    ymin, ymax = sorted((ymin, ymax))
    xmin, xmax = sorted((xmin, xmax))
    ymin, xmin, ymax, xmax = (int(round(min(max(v, 0), 1000))) for v in (ymin, xmin, ymax, xmax))
    if ymax - ymin < MIN_SIDE or xmax - xmin < MIN_SIDE:
        return None
    return [ymin, xmin, ymax, xmax]


def sector_for(box: list[int]) -> str:
    """4x4 grid: columns A-D (x), rows 1-4 (y), from box center."""
    cy = (box[0] + box[2]) / 2
    cx = (box[1] + box[3]) / 2
    col = min(int(cx // 250), 3)
    row = min(int(cy // 250), 3)
    return f"{'ABCD'[col]}{row + 1}"


def normalize_confidence(value) -> str:
    return CONFIDENCE_MAP.get(str(value).strip().lower(), "low")


def normalize_category(value) -> str:
    """One of the four review buckets; anything else (missing, misspelled) is an unknown anomaly."""
    code = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return code if code in CATEGORY_LABELS else "unknown_anomaly"


def coverage_mask(img: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """True where image B has real pixels. Pure black = outside camera coverage after the warp.
    None when the image is (almost) all black, e.g. synthetic test input: then nothing is filtered."""
    if img is None or img.size == 0:
        return None
    mask = (img.max(axis=2) if img.ndim == 3 else img) > BLACK_LEVEL
    return mask if mask.mean() >= 0.05 else None


def mostly_uncovered(box: list[int], mask: Optional[np.ndarray]) -> bool:
    if mask is None:
        return False
    h, w = mask.shape
    y0, x0 = int(box[0] / 1000 * h), int(box[1] / 1000 * w)
    y1, x1 = max(int(box[2] / 1000 * h), y0 + 1), max(int(box[3] / 1000 * w), x0 + 1)
    region = mask[y0:y1, x0:x1]
    return region.size > 0 and region.mean() < 1 - MAX_UNCOVERED


def to_result(raw: dict, image_b: Optional[np.ndarray] = None) -> AnalysisResult:
    """raw = parsed LLM JSON (dict). Malformed changes are dropped, never raised.
    With image_b, boxes lying mostly in black warp borders are dropped too."""
    mask = coverage_mask(image_b)
    changes = []
    for c in raw.get("changes") or []:
        if not isinstance(c, dict):
            continue
        box = clean_box(c.get("box"))
        if box is None or mostly_uncovered(box, mask):
            continue
        changes.append(Change(
            type=str(c.get("type") or "unknown"),
            description=str(c.get("description") or ""),
            location_text=str(c.get("location_text") or ""),
            confidence=normalize_confidence(c.get("confidence")),
            box=box,
            sector=sector_for(box),
            category=normalize_category(c.get("category")),
        ))
    return AnalysisResult(
        report_date=date.today().isoformat(),
        summary=str(raw.get("summary") or ""),
        changes=changes,
        recommendation=str(raw.get("recommendation") or ""),
    )
