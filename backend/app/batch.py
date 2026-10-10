"""Batch pipeline for one name-paired source pair (each a video or a still image):
frames -> cross-flight frame matching -> per matched pair: align, change heatmap, optional Gemini -> review records.

Only curated frame pairs with CV-detected differences reach Gemini, so a whole flight costs at most
2 calls x MATCH_MAX_PAIRS. Batches run one at a time on a worker thread: the CV work is CPU-bound.
"""
import hashlib
import logging
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import pipeline
from .alignment import align, warp_into
from .analysis import analyze, use_mock
from .contracts import AlignResult
from .ingest.media import load_still, media_kind
from .ingest.naming import MediaName
from .render import annotate
from .settings import ai_enabled
from .storage import batches as store
from .video.extract import FRAME_LIMIT, Frame, extract_frames, frame_max_side
from .video.match import MAX_PAIRS, MatchedPair, describe, match_flights

log = logging.getLogger(__name__)

BATCH_DIR = pipeline.OUTPUT_DIR / "batches"
HEAT_LEVEL = 0.2  # candidate_boxes' threshold: heat at or above it counts as changed
DEFAULT_CRITERIA = (
    "Any real physical change between the two frames: missing or moved equipment, vehicles and objects; new "
    "structures and construction; terrain and landscape changes; any other unusual change"
)


def batch_criteria() -> str:
    return os.getenv("BATCH_CRITERIA") or DEFAULT_CRITERIA


def max_pairs() -> int:
    return int(os.getenv("MATCH_MAX_PAIRS") or MAX_PAIRS)


def _clock(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def _write_jpg(path: Path, img: np.ndarray) -> None:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError(f"Could not encode {path.name}")
    buf.tofile(str(path))  # works for non-ASCII paths, unlike cv2.imwrite on Windows


def _read(frame: Frame) -> np.ndarray:
    return load_still(frame.path, frame_max_side())


def _source_frames(path: Path, work_dir: Path, label: str, warnings: list[str]) -> tuple[str, list[Frame]]:
    """Media kind from content; a still image is a one-frame sequence, a video is sampled by FFmpeg."""
    if not path.is_file():
        raise FileNotFoundError(f"Source {label} is gone: {path.name}")
    kind = media_kind(path)
    if kind == "image":
        return kind, [Frame(0, 0.0, path)]
    frames = extract_frames(path, work_dir)
    if len(frames) >= FRAME_LIMIT:
        warnings.append(f"Source {label} has more than {FRAME_LIMIT} frames at this rate; only the first "
                        f"{FRAME_LIMIT} were used.")
    return kind, frames


def _compare(
    batch_id: str, out_dir: Path, idx: int, fa: Frame, fb: Frame, match: MatchedPair, use_ai: bool,
    warnings: list[str],
) -> bool:
    """Align, diff and (optionally) analyze one matched pair; store it when it shows a difference."""
    img_a, img_b = _read(fa), _read(fb)
    label = f"A@{_clock(fa.t)} / B@{_clock(fb.t)}"
    aligned = align(img_a, img_b)
    if not aligned.ok:
        # Frame matching already verified this pair: fall back to its (coarser, 640 px) homography.
        aligned_b, valid_mask = warp_into(img_a.shape, img_b, match.homography)
        aligned = AlignResult(aligned_b=aligned_b, homography=np.asarray(match.homography).tolist(),
                              quality=float(np.clip(match.ncc, 0.0, 1.0)), ok=True, method="sift",
                              valid_mask=valid_mask)
        warnings.append(f"Pair {label}: full-resolution alignment failed; used the frame-matching homography.")
    heat, hints = pipeline.compute_heatmap(img_a, img_b, aligned, fill_uncovered=True)
    if heat is None or not hints:
        return False  # same ground, no pixel or structural difference

    result, source = pipeline.cv_result(hints), "cv"
    if use_ai:
        try:
            result = analyze(img_a, aligned.aligned_b, batch_criteria(), "en", hints=hints, aligned=True)
            source = "ai"
        except Exception as e:
            warnings.append(f"Pair {label}: Gemini failed ({str(e)[:120]}); heatmap regions kept instead.")
    if not result.changes:
        return False  # Gemini judged every heatmap region a false alarm

    pair_dir = out_dir / f"pair_{idx:02d}"
    pair_dir.mkdir(parents=True, exist_ok=True)
    _write_jpg(pair_dir / "a.jpg", img_a)
    _write_jpg(pair_dir / "aligned_b.jpg", aligned.aligned_b)
    _write_jpg(pair_dir / "heatmap.jpg", pipeline.heatmap_image(heat))
    _write_jpg(pair_dir / "annotated.jpg", annotate(aligned.aligned_b, result))
    url = f"/api/files/batches/{batch_id}/{pair_dir.name}"
    covered = aligned.valid_mask > 0 if aligned.valid_mask is not None else np.ones(heat.shape, bool)
    store.add_pair(batch_id, {
        "idx": idx, "frame_a": fa.index, "frame_b": fb.index, "time_a": fa.t, "time_b": fb.t,
        "inliers": match.inliers, "overlap": round(match.overlap, 4), "ssim": round(match.ssim, 4),
        "align_quality": aligned.quality, "align_method": aligned.method,
        "change_ratio": round(float((heat[covered] >= HEAT_LEVEL).mean()), 4) if covered.any() else 0.0,
        "source": source, "summary": result.summary, "recommendation": result.recommendation,
        "images": {
            "image_a_url": f"{url}/a.jpg", "aligned_b_url": f"{url}/aligned_b.jpg",
            "heatmap_url": f"{url}/heatmap.jpg", "annotated_url": f"{url}/annotated.jpg",
        },
    }, result.changes)
    return True


def process_batch(batch_id: str) -> None:
    """Run one batch end to end. Failures are recorded on the batch, never raised."""
    row = store.get_batch(batch_id)
    if row is None:
        return
    out_dir = BATCH_DIR / batch_id
    shutil.rmtree(out_dir, ignore_errors=True)  # a resumed or retried batch starts clean
    store.clear_pairs(batch_id)
    warnings: list[str] = []
    timings: dict[str, float] = {}
    t_start = time.perf_counter()
    try:
        store.update_batch(batch_id, status="running", stage="extracting", error_message=None)
        t0 = time.perf_counter()
        kind_a, frames_a = _source_frames(Path(row["path_a"]), out_dir / "frames_a", "A", warnings)
        kind_b, frames_b = _source_frames(Path(row["path_b"]), out_dir / "frames_b", "B", warnings)
        timings["extract"] = round(time.perf_counter() - t0, 3)
        store.update_batch(batch_id, stage="matching", kind_a=kind_a, kind_b=kind_b,
                           frames_a=len(frames_a), frames_b=len(frames_b), timings=timings)

        t0 = time.perf_counter()
        feats_a = [describe(_read(f)) for f in frames_a]
        feats_b = [describe(_read(f)) for f in frames_b]
        pairs = match_flights(feats_a, feats_b, mirror=kind_a == kind_b == "image", max_pairs=max_pairs())
        del feats_a, feats_b
        timings["match"] = round(time.perf_counter() - t0, 3)
        store.update_batch(batch_id, stage="comparing", matched_pairs=len(pairs), timings=timings)
        if not pairs:
            warnings.append("No frame of A shows the same ground as a frame of B: nothing to compare.")

        use_ai = bool(row["ai_enabled"])
        if use_ai and use_mock():
            use_ai = False
            warnings.append("AI requested but unavailable (MOCK_LLM=1 or no GEMINI_API_KEY): CV results only.")
        t0 = time.perf_counter()
        saved = 0
        for n, p in enumerate(pairs, 1):
            store.update_batch(batch_id, progress=f"{n}/{len(pairs)}")
            fa, fb = frames_a[p.a], frames_b[p.b]
            try:
                if _compare(batch_id, out_dir, saved + 1, fa, fb, p, use_ai, warnings):
                    saved += 1
            except Exception as e:  # one bad pair must not cost the rest of the batch
                log.exception("Batch %s: pair A@%s / B@%s failed", batch_id, _clock(fa.t), _clock(fb.t))
                warnings.append(f"Pair A@{_clock(fa.t)} / B@{_clock(fb.t)} failed: {str(e)[:120]}")
        timings["compare"] = round(time.perf_counter() - t0, 3)
        timings["total"] = round(time.perf_counter() - t_start, 3)
        store.finish_batch(batch_id, pairs_count=saved, timings=timings, warnings=warnings)
        log.info("Batch %s done: %d matched pairs, %d with differences", batch_id, len(pairs), saved)
    except Exception as e:
        log.exception("Batch %s failed", batch_id)
        store.fail_batch(batch_id, str(e) or type(e).__name__, warnings)
    finally:
        shutil.rmtree(out_dir / "frames_a", ignore_errors=True)
        shutil.rmtree(out_dir / "frames_b", ignore_errors=True)


def create_pair_batch(a: MediaName, b: MediaName, hash_a: str, hash_b: str, ai: Optional[bool] = None) -> Optional[str]:
    """New queued batch for a name pair, or None when the same content pair is already queued, running or done."""
    signature = hashlib.sha256(f"{hash_a}:{hash_b}".encode()).hexdigest()
    if store.find_active_batch(signature):
        return None
    batch_id = uuid.uuid4().hex[:12]
    store.create_batch(
        batch_id, site=a.key, name_a=a.path.name, name_b=b.path.name, tag_a=a.tag, tag_b=b.tag,
        path_a=str(a.path), path_b=str(b.path), signature=signature,
        ai_enabled=ai_enabled() if ai is None else ai,
    )
    return batch_id


def rerun_batch(batch_id: str) -> str:
    """Queue the same sources again with the current settings (e.g. AI switched on after a CV-only run)."""
    row = store.get_batch(batch_id)
    if row is None:
        raise KeyError(batch_id)
    for key in ("path_a", "path_b"):
        if not Path(row[key]).is_file():
            raise FileNotFoundError(f"Source file is gone: {Path(row[key]).name}")
    new_id = uuid.uuid4().hex[:12]
    store.create_batch(new_id, **{k: row[k] for k in (
        "site", "name_a", "name_b", "tag_a", "tag_b", "path_a", "path_b", "signature")}, ai_enabled=ai_enabled())
    return new_id


class BatchWorker:
    """Runs queued batches one at a time on a daemon thread, started on first use."""

    def __init__(self):
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def submit(self, batch_id: str) -> None:
        self._queue.put(batch_id)
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="batch-worker", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            batch_id = self._queue.get()
            try:
                process_batch(batch_id)
            finally:
                self._queue.task_done()


worker = BatchWorker()


def resume_interrupted() -> list[str]:
    """Re-queue batches a previous process left queued or running."""
    ids = store.reset_interrupted()
    for batch_id in ids:
        worker.submit(batch_id)
    return ids
