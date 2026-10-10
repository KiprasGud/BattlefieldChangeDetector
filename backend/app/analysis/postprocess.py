"""Validate and normalize raw LLM output into the frozen AnalysisResult contract."""
from datetime import date
from typing import Optional

from ..contracts import AnalysisResult, Change

MIN_SIDE = 5  # boxes thinner than this (in 0-1000 units) are dropped

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


def to_result(raw: dict) -> AnalysisResult:
    """raw = parsed LLM JSON (dict). Malformed changes are dropped, never raised."""
    changes = []
    for c in raw.get("changes") or []:
        if not isinstance(c, dict):
            continue
        box = clean_box(c.get("box"))
        if box is None:
            continue
        changes.append(Change(
            type=str(c.get("type") or "unknown"),
            description=str(c.get("description") or ""),
            location_text=str(c.get("location_text") or ""),
            confidence=normalize_confidence(c.get("confidence")),
            box=box,
            sector=sector_for(box),
        ))
    return AnalysisResult(
        report_date=date.today().isoformat(),
        summary=str(raw.get("summary") or ""),
        changes=changes,
        recommendation=str(raw.get("recommendation") or ""),
    )
