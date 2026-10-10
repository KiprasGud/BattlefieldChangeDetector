"""Offline analysis (MOCK_LLM=1).

Known demo pairs (shared/sample_data/<pair>/a.jpg with shared/fixtures/<pair>.json) are recognized by a
thumbnail signature of image A and return boxes on their real changes, filtered by the criteria, in the
requested language. Unknown images fall back to the generic fixture.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..contracts import AnalysisResult
from .postprocess import to_result

ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = ROOT / "shared" / "fixtures"
SAMPLES_DIR = ROOT / "shared" / "sample_data"
FIXTURE = FIXTURES_DIR / "sample_result.json"

MATCH_THRESHOLD = 6.0  # mean abs difference of 32x32 gray thumbnails (0-255)

# tag -> criteria keywords (English + Lithuanian stems)
TAG_KEYWORDS = {
    "tracks": ["track", "rut", "vėž", "vez", "takai", "takų"],
    "vehicle": ["vehicle", "truck", "transport", "equipment", "technik", "mašin"],
    "crater": ["crater", "shell", "impact", "explosion", "strike", "duob", "sprog", "pataik"],
    "earthworks": ["dig", "trench", "earthwork", "fortif", "kasim", "apkas", "žem"],
    "tree": ["tree", "felled", "clearing", "forest", "medž", "medz", "iškirst", "nuvirt", "mišk"],
    "cable": ["cable", "wire", "line", "kabel", "laid", "linij"],
    "structure": ["building", "structure", "roof", "barrier", "breach", "pastat", "stog", "užtvar"],
}

NO_MATCH_SUMMARY = {
    "en": "No changes matching the criteria were found in this sector.",
    "lt": "Šiame sektoriuje pokyčių, atitinkančių kriterijus, nerasta.",
}


def _signature(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)


@lru_cache(maxsize=1)
def _known_pairs() -> tuple:
    pairs = []
    for fixture in sorted(FIXTURES_DIR.glob("pair*.json")):
        img = cv2.imread(str(SAMPLES_DIR / fixture.stem / "a.jpg"))
        if img is not None:
            pairs.append((fixture.stem, _signature(img)))
    return tuple(pairs)


def match_pair(img_a: np.ndarray) -> Optional[str]:
    if img_a is None or img_a.size == 0:
        return None
    sig = _signature(img_a)
    best = min(((float(np.mean(np.abs(sig - s))), name) for name, s in _known_pairs()), default=None)
    return best[1] if best and best[0] < MATCH_THRESHOLD else None


def criteria_tags(criteria: str) -> set[str]:
    text = criteria.lower()
    return {tag for tag, words in TAG_KEYWORDS.items() if any(w in text for w in words)}


def _pick(value, lang: str) -> str:
    return value.get(lang) or value.get("en", "") if isinstance(value, dict) else str(value)


def analyze_mock(img_a, aligned_b, criteria: str, lang: str = "en") -> AnalysisResult:
    pair = match_pair(img_a)
    if pair is None:
        return to_result(json.loads(FIXTURE.read_text(encoding="utf-8")))

    data = json.loads((FIXTURES_DIR / f"{pair}.json").read_text(encoding="utf-8"))
    wanted = criteria_tags(criteria)
    changes = [c for c in data["changes"] if not wanted or wanted & set(c.get("tags", []))]
    raw = {
        "summary": _pick(data["summary"], lang) if changes else NO_MATCH_SUMMARY.get(lang, NO_MATCH_SUMMARY["en"]),
        "recommendation": _pick(data["recommendation"], lang) if changes else "",
        "changes": [
            {
                "type": _pick(c["type"], lang),
                "description": _pick(c["description"], lang),
                "location_text": _pick(c["location_text"], lang),
                "confidence": c["confidence"],
                "box": c["box"],
            }
            for c in changes
        ],
    }
    return to_result(raw)
