"""Offline analysis (MOCK_LLM=1).

Known demo pairs (shared/sample_data/<pair>/a.jpg with shared/fixtures/<pair>.json) are recognized visually in
image A, whatever its resolution, crop, rotation or mirroring, and return boxes on their real changes, mapped into
the uploaded frame, filtered by the criteria, in the requested language. Unknown images fall back to the generic
fixture.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..alignment import IMREAD_PIXELS, estimate_homography, extract_features
from ..contracts import AnalysisResult
from .postprocess import clean_box, to_result
from .presets import PRESETS, split_criteria

ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = ROOT / "shared" / "fixtures"
SAMPLES_DIR = ROOT / "shared" / "sample_data"
FIXTURE = FIXTURES_DIR / "sample_result.json"

MIN_VISIBLE = 0.5  # a mapped fixture box must keep at least half its area inside the uploaded image
MATCH_SIDE, MATCH_FEATURES = 640, 2000  # recognition only needs a coarse homography: smaller = faster

# tag -> criteria keywords (English + Lithuanian stems)
TAG_KEYWORDS = {
    "tracks": ["track", "rut", "vėž", "vez", "takai", "takų"],
    "vehicle": ["vehicle", "truck", "transport", "equipment", "technik", "mašin"],
    "crater": ["crater", "shell", "impact", "explosion", "strike", "duob", "sprog", "pataik"],
    "earthworks": ["dig", "trench", "earthwork", "fortif", "kasim", "apkas", "žem"],
    "tree": ["tree", "felled", "clearing", "forest", "medž", "medz", "iškirst", "nuvirt", "mišk"],
    "cable": ["cable", "wire", "line", "kabel", "laid", "linij"],
    "structure": ["building", "structure", "roof", "barrier", "breach", "damage", "rubble", "destroy", "pastat",
                  "stog", "užtvar", "griuv"],
    "camouflage": ["camouf", "netting", "conceal", "maskuot", "maskavim"],
}

NO_MATCH_SUMMARY = {
    "en": "No changes matching the criteria were found in this sector.",
    "lt": "Šiame sektoriuje pokyčių, atitinkančių kriterijus, nerasta.",
}


@lru_cache(maxsize=1)
def _known_pairs() -> tuple:
    pairs = []
    for fixture in sorted(FIXTURES_DIR.glob("pair*.json")):
        img = cv2.imread(str(SAMPLES_DIR / fixture.stem / "a.jpg"), IMREAD_PIXELS)
        if img is not None:
            pairs.append((fixture.stem, extract_features(img, MATCH_SIDE, MATCH_FEATURES)))
    return tuple(pairs)


def match_pair(img_a: np.ndarray) -> Optional[tuple[str, np.ndarray, tuple]]:
    """(pair name, homography sample A -> img_a, sample A shape) for the known pair visible in img_a, else None."""
    if img_a is None or img_a.size == 0:
        return None
    target = extract_features(img_a, MATCH_SIDE, MATCH_FEATURES)
    best = None
    for name, sample in _known_pairs():
        reg = estimate_homography(None, None, src_features=sample, dst_features=target)
        if reg is not None and (best is None or reg.inliers > best[0]):
            best = (reg.inliers, name, reg.H, sample.full_shape)
    return best[1:] if best else None


def map_box(box: list[int], H: np.ndarray, src_shape, dst_shape) -> Optional[list[int]]:
    """0-1000 box in the sample frame -> 0-1000 box in the uploaded frame; None if it falls mostly outside."""
    hs, ws = src_shape[:2]
    hd, wd = dst_shape[:2]
    y0, x0, y1, x1 = (v / 1000 for v in box)
    corners = np.float64([[x0 * ws, y0 * hs], [x1 * ws, y0 * hs], [x1 * ws, y1 * hs], [x0 * ws, y1 * hs]])
    proj = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), H).reshape(-1, 2)
    (px0, py0), (px1, py1) = proj.min(axis=0), proj.max(axis=0)
    cx0, cy0, cx1, cy1 = max(px0, 0), max(py0, 0), min(px1, wd), min(py1, hd)
    full = (px1 - px0) * (py1 - py0)
    if full <= 0 or cx1 <= cx0 or cy1 <= cy0 or (cx1 - cx0) * (cy1 - cy0) < MIN_VISIBLE * full:
        return None
    return clean_box([cy0 / hd * 1000, cx0 / wd * 1000, cy1 / hd * 1000, cx1 / wd * 1000])


def criteria_tags(criteria: str) -> set[str]:
    """Preset tags plus keyword tags of the free text only (preset labels would match extra tags)."""
    preset_ids, custom = split_criteria(criteria)
    text = custom.lower()
    tags = {tag for pid in preset_ids for tag in PRESETS[pid].tags}
    return tags | {tag for tag, words in TAG_KEYWORDS.items() if any(w in text for w in words)}


def _pick(value, lang: str) -> str:
    return value.get(lang) or value.get("en", "") if isinstance(value, dict) else str(value)


def analyze_mock(img_a: np.ndarray, aligned_b: np.ndarray, criteria: str, lang: str = "en") -> AnalysisResult:
    match = match_pair(img_a)
    if match is None:
        return to_result(json.loads(FIXTURE.read_text(encoding="utf-8")), image_b=aligned_b)

    pair, H, sample_shape = match
    data = json.loads((FIXTURES_DIR / f"{pair}.json").read_text(encoding="utf-8"))
    wanted = criteria_tags(criteria)
    changes = []
    for c in data["changes"]:
        if wanted and not wanted & set(c.get("tags", [])):
            continue
        box = map_box(c["box"], H, sample_shape, img_a.shape)
        if box is not None:
            changes.append({**c, "box": box})
    raw = {
        "summary": _pick(data["summary"], lang) if changes else NO_MATCH_SUMMARY.get(lang, NO_MATCH_SUMMARY["en"]),
        "recommendation": _pick(data["recommendation"], lang) if changes else "",
        "changes": [
            {
                "type": _pick(c["type"], lang),
                "category": c.get("category"),
                "description": _pick(c["description"], lang),
                "location_text": _pick(c["location_text"], lang),
                "confidence": c["confidence"],
                "box": c["box"],
            }
            for c in changes
        ],
    }
    return to_result(raw, image_b=aligned_b)
