"""FROZEN shared contracts. Change only via a small PR announced to the team.

Box convention: [ymin, xmin, ymax, xmax], normalized 0-1000, origin top-left of image A frame.
"""
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal["high", "medium", "low"]
AlignMethod = Literal["sift", "ecc", "none"]
Category = Literal["missing_object", "new_structure", "terrain_change", "unknown_anomaly"]

CATEGORY_LABELS = {
    "missing_object": "Missing Equipment/Objects",
    "new_structure": "New Structures/Construction",
    "terrain_change": "Terrain/Landscape Changes",
    "unknown_anomaly": "Unknown Anomaly",
}


class Change(BaseModel):
    type: str                       # e.g. "crater", "tracks", "fallen tree"
    description: str                # what exactly changed
    location_text: str              # e.g. "upper right, near road junction"
    confidence: Confidence
    box: list[int] = Field(min_length=4, max_length=4)  # [ymin, xmin, ymax, xmax] 0-1000
    sector: Optional[str] = None    # grid label, e.g. "B4"
    category: Optional[Category] = None  # review bucket, see CATEGORY_LABELS


class AnalysisResult(BaseModel):
    report_date: str                # YYYY-MM-DD
    summary: str                    # 2-sentence situation assessment
    changes: list[Change]
    recommendation: str


class AlignResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    aligned_b: np.ndarray           # image B warped into A's frame (BGR uint8, same size as A)
    homography: Optional[list[list[float]]] = None  # 3x3, None if unavailable
    quality: float = 0.0            # 0-1 (e.g. inlier ratio)
    ok: bool = True                 # False -> pipeline warns, continues unaligned
    method: AlignMethod = "none"    # "sift", "ecc", or "none"
    valid_mask: Optional[np.ndarray] = None  # uint8 255 = valid pixels of warped B


class AnalyzeResponse(BaseModel):
    job_id: str
    result: AnalysisResult
    align_quality: float
    align_ok: bool
    images: dict[str, str]          # {"aligned_b_url": ..., "annotated_url": ..., "image_a_url": ..., "heatmap_url": ...}
    timings: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
