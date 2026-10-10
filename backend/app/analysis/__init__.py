import os
from functools import partial
from typing import Optional

from . import cache, tiling
from .gemini_client import analyze_with_gemini, make_client, model_name, thinking_level, verify_changes, verify_enabled
from .mock import analyze_mock
from .prompts import PROMPT_VERSION


def use_mock() -> bool:
    return os.getenv("MOCK_LLM", "1") == "1" or not os.getenv("GEMINI_API_KEY")


def analyze(
    img_a,
    aligned_b,
    criteria: str,
    lang: str = "en",
    hints: Optional[list[list[int]]] = None,
    aligned: bool = True,
):
    """PERSON 2 owns this package. Returns AnalysisResult.

    hints: optional candidate boxes (0-1000) from the change heatmap; Gemini verifies them.
    aligned: False when registration failed, so the prompt stops claiming pixel correspondence.
    MOCK_LLM=1 (or no key) -> offline fixtures (no network).
    Large images (> ANALYSIS_TILE_MIN_SIDE px) are analyzed in overlapping tiles, then verified once.
    Results are cached on disk (ANALYSIS_CACHE=0 disables).
    """
    if use_mock():
        return analyze_mock(img_a, aligned_b, criteria, lang)

    tiled = tiling.should_tile(img_a)
    settings = {
        "model": model_name(), "thinking": thinking_level(), "prompt": PROMPT_VERSION, "aligned": aligned,
        "verify": verify_enabled(), "tiled": tiled, "grid": tiling.tile_grid(),
    }
    key = cache.make_key(img_a, aligned_b, criteria, lang, hints, settings) if cache.enabled() else None
    if key and (hit := cache.get(key)):
        return hit

    client = make_client()
    if tiled:
        # Tiles skip their own verification: one pass over the merged list, on full-resolution crops.
        detect = partial(analyze_with_gemini, client=client, verify=False, aligned=aligned)
        result = tiling.analyze_tiled(img_a, aligned_b, criteria, lang, hints, detect)
        if verify_enabled():
            result = verify_changes(client, img_a, aligned_b, criteria, result)
    else:
        result = analyze_with_gemini(img_a, aligned_b, criteria, lang, hints, client=client, aligned=aligned)

    if key:
        cache.put(key, result)
    return result


__all__ = ["analyze"]
