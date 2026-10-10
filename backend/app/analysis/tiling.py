"""Tiled analysis for large images: small objects (cables, tracks) vanish when a 4000 px photo is shrunk
to the model's input size. We run one full-image pass (summary, big changes) plus one pass per overlapping
tile, map tile boxes back to full-image coordinates and merge duplicates with NMS."""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import numpy as np

from ..contracts import AnalysisResult, Change
from .postprocess import clean_box, sector_for, unique_labels

log = logging.getLogger(__name__)

CONF_RANK = {"high": 2, "medium": 1, "low": 0}


def tile_grid() -> int:
    return int(os.getenv("ANALYSIS_TILE_GRID", "4"))


def tile_min_side() -> int:
    return int(os.getenv("ANALYSIS_TILE_MIN_SIDE", "2000"))


def should_tile(img: np.ndarray) -> bool:
    return os.getenv("ANALYSIS_TILING", "1") == "1" and max(img.shape[:2]) > tile_min_side() and tile_grid() > 1


def make_tiles(h: int, w: int, grid: int, overlap: float = 0.15) -> list[tuple[int, int, int, int]]:
    """Pixel tiles (y0, x0, y1, x1) covering the image, each extended by `overlap` of a cell on every side."""
    tiles = []
    ch, cw = h / grid, w / grid
    oy, ox = ch * overlap, cw * overlap
    for r in range(grid):
        for c in range(grid):
            y0, x0 = max(0, int(r * ch - oy)), max(0, int(c * cw - ox))
            y1, x1 = min(h, int((r + 1) * ch + oy)), min(w, int((c + 1) * cw + ox))
            tiles.append((y0, x0, y1, x1))
    return tiles


def tile_box_to_full(box: list[int], tile: tuple[int, int, int, int], h: int, w: int) -> Optional[list[int]]:
    """0-1000 box inside a tile -> 0-1000 box in the full image."""
    y0, x0, y1, x1 = tile
    th, tw = y1 - y0, x1 - x0
    full = [
        (y0 + box[0] / 1000 * th) / h * 1000,
        (x0 + box[1] / 1000 * tw) / w * 1000,
        (y0 + box[2] / 1000 * th) / h * 1000,
        (x0 + box[3] / 1000 * tw) / w * 1000,
    ]
    return clean_box(full)


def full_box_to_tile(box: list[int], tile: tuple[int, int, int, int], h: int, w: int) -> Optional[list[int]]:
    """0-1000 full-image box -> 0-1000 box inside the tile (clipped), None if it lies outside."""
    y0, x0, y1, x1 = tile
    th, tw = y1 - y0, x1 - x0
    local = [
        (box[0] / 1000 * h - y0) / th * 1000,
        (box[1] / 1000 * w - x0) / tw * 1000,
        (box[2] / 1000 * h - y0) / th * 1000,
        (box[3] / 1000 * w - x0) / tw * 1000,
    ]
    if local[2] <= 0 or local[3] <= 0 or local[0] >= 1000 or local[1] >= 1000:
        return None
    return clean_box(local)


def iou(a: list[int], b: list[int]) -> float:
    iy = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    ix = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iy * ix
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms(changes: list[Change], iou_threshold: float = 0.3) -> list[Change]:
    """Keep the most confident (then largest) box of every overlapping group."""
    ordered = sorted(
        changes,
        key=lambda c: (CONF_RANK.get(c.confidence, 0), (c.box[2] - c.box[0]) * (c.box[3] - c.box[1])),
        reverse=True,
    )
    kept: list[Change] = []
    for c in ordered:
        if all(iou(c.box, k.box) < iou_threshold for k in kept):
            kept.append(c)
    return kept


def analyze_tiled(
    img_a: np.ndarray,
    aligned_b: np.ndarray,
    criteria: str,
    lang: str,
    hints: Optional[list[list[int]]],
    analyze_fn: Callable[..., AnalysisResult],
    max_workers: int = 4,
) -> AnalysisResult:
    """analyze_fn(img_a, img_b, criteria, lang, hints) -> AnalysisResult; called for the full image and every tile.
    A failing tile is logged and skipped; a failing full-image pass raises."""
    h, w = img_a.shape[:2]
    tiles = make_tiles(h, w, tile_grid())

    def run_tile(tile):
        tile_hints = [b for b in (full_box_to_tile(h_, tile, h, w) for h_ in hints or []) if b]
        y0, x0, y1, x1 = tile
        try:
            res = analyze_fn(img_a[y0:y1, x0:x1], aligned_b[y0:y1, x0:x1], criteria, lang, tile_hints or None)
        except Exception as e:
            log.warning("Tile %s failed: %s", tile, e)
            return []
        out = []
        for c in res.changes:
            box = tile_box_to_full(c.box, tile, h, w)
            if box:
                out.append(c.model_copy(update={"box": box, "sector": sector_for(box)}))
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        full_future = pool.submit(analyze_fn, img_a, aligned_b, criteria, lang, hints)
        tile_results = list(pool.map(run_tile, tiles))
        full = full_future.result()

    # Tiles label independently, so the same label can come back from two tiles.
    merged = unique_labels(nms(list(full.changes) + [c for tile in tile_results for c in tile]))
    log.info("Tiled analysis: %d full-image + %d tile detections -> %d after NMS",
             len(full.changes), sum(map(len, tile_results)), len(merged))
    return full.model_copy(update={"changes": merged})
