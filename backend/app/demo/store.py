"""Demo cache: finished analysis jobs frozen as presentation scenes (the exact images + the AI's JSON output).

Layout of DEMO_CACHE_DIR (default <repo>/demo_cache):
    manifest.json             {"version": 1, "updated_at": ..., "scenes": [scene ids in presentation order]}
    <scene id>/scene.json     the scene record: title, criteria, model, alignment and the AI result verbatim
    <scene id>/image_a.jpg, aligned_b.jpg, annotated.jpg    the job's output images, all in image A's frame
    <scene id>/source_a.*, source_b.*                       the exact uploaded originals, byte for byte
The presentation view reads these files statically; only the demo prep server writes them. The AI output is
stored as the model returned it: a wrong detection is fixed by re-prompting and caching a new run, never by hand."""
import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import cv2

from ..alignment import IMREAD_PIXELS
from ..analysis.gemini_client import model_name
from ..analysis.presets import split_criteria
from ..analysis.prompts import PROMPT_VERSION
from ..pipeline import OUTPUT_DIR

log = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "demo_cache"
MANIFEST = "manifest.json"
SCENE_JSON = "scene.json"
JOB_FILES = ("image_a.jpg", "aligned_b.jpg", "annotated.jpg")  # from backend/output/<job id>/; no heatmap
SOURCE_KEYS = ("source_a", "source_b")
SOURCE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SCENE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")  # a plain folder name, never a path
BUSY_RETRIES, BUSY_DELAY_S = 20, 0.05  # a busy file (Windows) is retried for up to a second

_lock = threading.Lock()  # one writer at a time: the manifest and the scene folders change together


class JobNotReady(RuntimeError):
    """The job cannot be cached (yet): still running, failed, or its output files were pruned."""


def cache_dir() -> Path:
    path = Path(os.getenv("DEMO_CACHE_DIR") or DEFAULT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _retry(action: Callable[[], Any]) -> Any:
    """Run a file operation, retrying for up to a second while Windows reports the file busy: a server reading
    it, the search indexer or antivirus can hold it open for a moment, and an open file cannot be replaced."""
    for attempt in range(BUSY_RETRIES):
        try:
            return action()
        except PermissionError:
            if attempt == BUSY_RETRIES - 1:
                raise
            time.sleep(BUSY_DELAY_S)


def _write_json(path: Path, data: Any) -> None:
    """Write through a temp file and an atomic rename: a reader never sees half a file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        _retry(lambda: os.replace(tmp, path))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def read_order() -> list[str]:
    """Scene ids in presentation order."""
    path = cache_dir() / MANIFEST
    if not path.is_file():
        return []
    try:
        scenes = json.loads(path.read_text(encoding="utf-8")).get("scenes", [])
    except (OSError, ValueError, AttributeError) as e:
        # Never guess: rewriting a manifest we cannot read would drop every scene from the presentation.
        raise RuntimeError(f"{path} is unreadable: {e}") from e
    return [s for s in scenes if isinstance(s, str) and SCENE_ID.fullmatch(s)]


def _write_order(order: list[str]) -> None:
    _write_json(cache_dir() / MANIFEST, {"version": 1, "updated_at": _now(), "scenes": order})


def _read_scene(scene_id: str) -> Optional[dict[str, Any]]:
    path = cache_dir() / scene_id / SCENE_JSON
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Skipping demo scene %s: %s", scene_id, e)
        return None


def list_scenes() -> list[dict[str, Any]]:
    """Scene records in presentation order; a scene whose folder is gone or broken is skipped."""
    return [scene for scene in map(_read_scene, read_order()) if scene is not None]


def _slug(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")[:32].strip("-") or "scene"


def _new_id(title: str, taken: list[str]) -> str:
    """Readable folder name: the title's slug plus a random suffix."""
    while True:
        scene_id = f"{_slug(title)}-{uuid.uuid4().hex[:6]}"
        if scene_id not in taken and not (cache_dir() / scene_id).exists():
            return scene_id


def result_source(warnings: list[str]) -> str:
    """Where a job's detections came from, read from the pipeline's warnings: "gemini", "fixtures" (offline mock,
    also the automatic fallback when Gemini fails) or "ai_off" (AI step switched off: no detections)."""
    if any(w.startswith("AI step disabled") for w in warnings):
        return "ai_off"
    if any(w.startswith("OFFLINE MODE") for w in warnings):
        return "fixtures"
    return "gemini"


def save_scene(
    job: dict[str, Any],
    title: str,
    subtitle: str = "",
    sources: Optional[dict[str, tuple[str, bytes]]] = None,
    scene_id: Optional[str] = None,
) -> dict[str, Any]:
    """Cache State: freeze a finished job (GET /api/jobs/{id} record) as a scene and return its record.
    sources: {"source_a" | "source_b": (file name, bytes)}, the exact original uploads.
    scene_id: replace that scene in place (same position in the presentation); None appends a new scene.
    ValueError: no title. KeyError: unknown scene_id. JobNotReady: unfinished job or pruned output."""
    title, subtitle = title.strip(), subtitle.strip()
    if not title:
        raise ValueError("A scene needs a title: it is shown to the audience.")
    job_id = job.get("job_id")
    if job.get("status") != "done" or not job.get("result"):
        raise JobNotReady(f"Job {job_id} has not finished.")
    job_dir = OUTPUT_DIR / str(job_id)
    missing = [name for name in JOB_FILES if not (job_dir / name).is_file()]
    if missing:
        raise JobNotReady(f"The output of job {job_id} is gone ({', '.join(missing)}): run the analysis again.")

    with _lock:
        order = read_order()
        if scene_id is not None and scene_id not in order:
            raise KeyError(scene_id)
        scene_id = scene_id or _new_id(title, order)
        root = cache_dir()
        tmp = root / f".{scene_id}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            files: dict[str, str] = {}
            for name in JOB_FILES:
                shutil.copyfile(job_dir / name, tmp / name)
                files[Path(name).stem] = name
            for key in SOURCE_KEYS:
                if key not in (sources or {}):
                    continue
                filename, data = sources[key]
                suffix = Path(filename).suffix.lower()
                name = key + (suffix if suffix in SOURCE_SUFFIXES else ".img")
                (tmp / name).write_bytes(data)
                files[key] = name
            frame = cv2.imread(str(tmp / "image_a.jpg"), IMREAD_PIXELS)
            if frame is None:
                raise JobNotReady(f"The image A of job {job_id} cannot be read: run the analysis again.")
            presets, query = split_criteria(job.get("criteria") or "")
            source = result_source(job.get("warnings") or [])
            scene = {
                "id": scene_id,
                "title": title,
                "subtitle": subtitle,
                "cached_at": _now(),
                "source_job": job_id,
                "criteria": job.get("criteria") or "",
                "presets": presets,
                "query": query,
                "lang": job.get("lang") or "en",
                "source": source,
                "model": model_name() if source == "gemini" else None,
                "prompt_version": PROMPT_VERSION,
                "size": {"w": int(frame.shape[1]), "h": int(frame.shape[0])},
                "align": {
                    "ok": bool(job.get("align_ok")),
                    "quality": job.get("align_quality") or 0.0,
                    "method": job.get("align_method") or "none",
                },
                "warnings": job.get("warnings") or [],
                "timings": job.get("timings") or {},
                "result": job["result"],
                "files": files,
            }
            _write_json(tmp / SCENE_JSON, scene)
            target = root / scene_id
            if target.exists():
                _retry(lambda: shutil.rmtree(target))
            _retry(lambda: tmp.rename(target))
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        if scene_id not in order:
            try:
                _write_order(order + [scene_id])
            except BaseException:
                shutil.rmtree(target, ignore_errors=True)  # no folder the manifest does not list
                raise
    return scene


def rename_scene(scene_id: str, title: Optional[str] = None, subtitle: Optional[str] = None) -> dict[str, Any]:
    """Change what the audience reads above a scene; its images and AI output stay as cached."""
    with _lock:
        scene = _read_scene(scene_id) if scene_id in read_order() else None
        if scene is None:
            raise KeyError(scene_id)
        if title is not None:
            if not title.strip():
                raise ValueError("A scene needs a title: it is shown to the audience.")
            scene["title"] = title.strip()
        if subtitle is not None:
            scene["subtitle"] = subtitle.strip()
        _write_json(cache_dir() / scene_id / SCENE_JSON, scene)
    return scene


def set_order(scene_ids: list[str]) -> list[str]:
    """New presentation order; it must list every cached scene exactly once."""
    with _lock:
        if sorted(scene_ids) != sorted(read_order()):
            raise ValueError("The order must list every cached scene exactly once.")
        _write_order(list(scene_ids))
    return list(scene_ids)


def delete_scene(scene_id: str) -> None:
    with _lock:
        order = read_order()
        if scene_id not in order:
            raise KeyError(scene_id)
        _write_order([s for s in order if s != scene_id])  # out of the presentation first, then off the disk
        shutil.rmtree(cache_dir() / scene_id, ignore_errors=True)
