"""Disk cache of Gemini results so repeated demo runs cost no quota and return instantly.
Key = image contents + criteria + lang + hints + every setting that changes the answer."""
import hashlib
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

from ..contracts import AnalysisResult

log = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parent / ".cache"


def enabled() -> bool:
    return os.getenv("ANALYSIS_CACHE", "1") == "1"


def cache_dir() -> Path:
    path = Path(os.getenv("ANALYSIS_CACHE_DIR", str(DEFAULT_DIR)))
    path.mkdir(parents=True, exist_ok=True)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    return path


def make_key(img_a: np.ndarray, aligned_b: np.ndarray, criteria: str, lang: str, hints, settings: dict) -> str:
    h = hashlib.sha256()
    for img in (img_a, aligned_b):
        h.update(str(img.shape).encode())
        h.update(np.ascontiguousarray(img).tobytes())
    hints = [[int(v) for v in box] for box in hints or []]
    meta = {"criteria": criteria.strip().lower(), "lang": lang, "hints": hints, **settings}
    h.update(json.dumps(meta, sort_keys=True).encode())
    return h.hexdigest()


def get(key: str) -> Optional[AnalysisResult]:
    path = cache_dir() / f"{key}.json"
    if not path.exists():
        return None
    try:
        result = AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Ignoring broken cache entry %s: %s", path.name, e)
        return None
    return result.model_copy(update={"report_date": date.today().isoformat()})


def put(key: str, result: AnalysisResult) -> None:
    try:
        (cache_dir() / f"{key}.json").write_text(result.model_dump_json(), encoding="utf-8")
    except OSError as e:
        log.warning("Could not write cache: %s", e)
