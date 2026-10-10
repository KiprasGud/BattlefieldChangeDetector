"""Batch pipeline for one project: every epoch of a naming key (Site_A_Day1, _Day2, _Day5) in one batch, one leg per
consecutive epoch pair (Day1 -> Day2, Day2 -> Day5); each source is a video or a still image. Per leg:
frames -> cross-flight frame matching -> per matched pair: align, change heatmap, optional Gemini -> review records.

A new epoch of a project already batched is appended to that batch as a new leg; finished legs and their reviews stay.
Only curated frame pairs with CV-detected differences reach Gemini, so a leg costs at most 2 calls x MATCH_MAX_PAIRS.
Batches run one at a time on a worker thread (the CV work is CPU-bound); the worker can be paused.
"""
import hashlib
import logging
import os
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import pipeline
from .alignment import align, warp_into
from .analysis import analyze, use_mock
from .analysis.presets import build_criteria
from .contracts import AlignResult
from .ingest.media import load_still, media_kind
from .ingest.naming import MediaName, pairs_for
from .render import annotate
from .settings import ai_enabled, auto_batch_enabled, batch_target
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

# Guards the queue state: picking a batch's next leg (or finishing it) vs appending legs vs clearing the queue.
_lock = threading.Lock()


def batch_criteria() -> str:
    """Criteria for batches queued now: the dashboard's target classes and query (same text as /api/analyze builds),
    else BATCH_CRITERIA, else any real change."""
    return build_criteria(*batch_target()) or os.getenv("BATCH_CRITERIA") or DEFAULT_CRITERIA


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
    batch_id: str, out_dir: Path, leg_idx: int, idx: int, fa: Frame, fb: Frame, match: MatchedPair, use_ai: bool,
    criteria: str, warnings: list[str],
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
            result = analyze(img_a, aligned.aligned_b, criteria, "en", hints=hints, aligned=True)
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
        "leg_idx": leg_idx, "idx": idx, "frame_a": fa.index, "frame_b": fb.index, "time_a": fa.t, "time_b": fb.t,
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


def _leg_label(leg: dict) -> str:
    return f"{leg['tag_a']}→{leg['tag_b']}"


def _process_leg(batch_id: str, out_dir: Path, leg: dict, use_ai: bool, criteria: str) -> None:
    """Match and compare one leg's two sources. Failures are recorded on the leg, never raised."""
    for idx in store.clear_leg_pairs(batch_id, leg["idx"]):  # a resumed or retried leg starts clean
        shutil.rmtree(out_dir / f"pair_{idx:02d}", ignore_errors=True)
    leg_dir = out_dir / f"leg_{leg['idx']:02d}"
    label = _leg_label(leg)
    warnings: list[str] = []
    timings: dict[str, float] = {}
    t_start = time.perf_counter()
    try:
        store.update_batch(batch_id, stage="extracting", progress=label)
        t0 = time.perf_counter()
        kind_a, frames_a = _source_frames(Path(leg["path_a"]), leg_dir / "frames_a", "A", warnings)
        kind_b, frames_b = _source_frames(Path(leg["path_b"]), leg_dir / "frames_b", "B", warnings)
        timings["extract"] = round(time.perf_counter() - t0, 3)
        store.update_leg(leg["id"], kind_a=kind_a, kind_b=kind_b, frames_a=len(frames_a), frames_b=len(frames_b))
        store.update_batch(batch_id, stage="matching")

        t0 = time.perf_counter()
        feats_a = [describe(_read(f)) for f in frames_a]
        feats_b = [describe(_read(f)) for f in frames_b]
        pairs = match_flights(feats_a, feats_b, mirror=kind_a == kind_b == "image", max_pairs=max_pairs())
        del feats_a, feats_b
        timings["match"] = round(time.perf_counter() - t0, 3)
        store.update_leg(leg["id"], matched_pairs=len(pairs))
        store.update_batch(batch_id, stage="comparing")
        if not pairs:
            warnings.append("No frame of A shows the same ground as a frame of B: nothing to compare.")

        t0 = time.perf_counter()
        saved = 0
        for n, p in enumerate(pairs, 1):
            store.update_batch(batch_id, progress=f"{label} {n}/{len(pairs)}")
            fa, fb = frames_a[p.a], frames_b[p.b]
            try:
                if _compare(batch_id, out_dir, leg["idx"], store.next_pair_idx(batch_id), fa, fb, p, use_ai,
                            criteria, warnings):
                    saved += 1
            except Exception as e:  # one bad pair must not cost the rest of the leg
                log.exception("Batch %s %s: pair A@%s / B@%s failed", batch_id, label, _clock(fa.t), _clock(fb.t))
                warnings.append(f"Pair A@{_clock(fa.t)} / B@{_clock(fb.t)} failed: {str(e)[:120]}")
        timings["compare"] = round(time.perf_counter() - t0, 3)
        timings["total"] = round(time.perf_counter() - t_start, 3)
        store.update_leg(leg["id"], status="done", timings=timings, warnings=warnings)
        log.info("Batch %s %s done: %d matched pairs, %d with differences", batch_id, label, len(pairs), saved)
    except Exception as e:
        log.exception("Batch %s %s failed", batch_id, label)
        store.update_leg(leg["id"], status="error", error_message=(str(e) or type(e).__name__)[:500],
                         timings=timings, warnings=warnings)
    finally:
        shutil.rmtree(leg_dir, ignore_errors=True)


def _finish(batch_id: str, ai_warning: Optional[str]) -> None:
    """Roll the legs up into the batch: done when at least one leg is, error when every leg failed."""
    legs = store.list_legs(batch_id)
    warnings = [ai_warning] if ai_warning else []
    timings: dict[str, float] = {}
    for leg in legs:
        warnings += [f"{_leg_label(leg)}: {w}" for w in leg["warnings"]]
        if leg["status"] == "error":
            warnings.append(f"{_leg_label(leg)} failed: {leg['error_message']}")
        for k, v in leg["timings"].items():
            timings[k] = round(timings.get(k, 0.0) + v, 3)
    done = [leg for leg in legs if leg["status"] == "done"]
    if not done:
        message = "; ".join(f"{_leg_label(leg)}: {leg['error_message']}" for leg in legs) or "No legs to compare."
        store.fail_batch(batch_id, message, warnings)
        return

    def total(key: str) -> int:
        return sum(leg[key] or 0 for leg in done)

    store.finish_batch(
        batch_id, pairs_count=store.count_pairs(batch_id), timings=timings, warnings=warnings,
        kind_a=legs[0]["kind_a"], kind_b=legs[-1]["kind_b"], frames_a=total("frames_a"), frames_b=total("frames_b"),
        matched_pairs=total("matched_pairs"),
    )


def process_batch(batch_id: str) -> None:
    """Run every pending leg of a queued batch, in order; legs appended while it runs are picked up too.
    Failures are recorded on the leg or the batch, never raised. A batch no longer queued (cleared) is skipped."""
    with _lock:
        row = store.get_batch(batch_id)
        if row is None or row["status"] != "queued":
            return
        store.update_batch(batch_id, status="running", stage="extracting", progress="", error_message=None)
    use_ai, ai_warning = bool(row["ai_enabled"]), None
    criteria = row["criteria"] or batch_criteria()  # batches from before per-batch criteria have none stored
    if use_ai and use_mock():
        use_ai = False
        ai_warning = "AI requested but unavailable (MOCK_LLM=1 or no GEMINI_API_KEY): CV results only."
    out_dir = BATCH_DIR / batch_id
    try:
        while True:
            with _lock:
                leg = store.next_pending_leg(batch_id)
                if leg is None:
                    _finish(batch_id, ai_warning)
                    return
                store.update_leg(leg["id"], status="running", error_message=None)
            _process_leg(batch_id, out_dir, leg, use_ai, criteria)
    except Exception as e:
        log.exception("Batch %s failed", batch_id)
        store.fail_batch(batch_id, str(e) or type(e).__name__)


def _signature(*hashes: str) -> str:
    return hashlib.sha256(":".join(hashes).encode()).hexdigest()


def queue_project(items: list[MediaName], hashes: dict[Path, str], ai: Optional[bool] = None,
                  only: Optional[tuple[str, str]] = None) -> Optional[str]:
    """Put a project's epochs (one site, any order) into its batch: a new batch with one leg per consecutive pair, or
    the project's existing batch with the legs it does not have yet (failed legs of the same content are retried).
    only=(name_a, name_b) adds just that consecutive pair. Returns the batch id when it must be submitted to the
    worker: new, or finished and now re-opened."""
    legs = pairs_for(items)
    if not legs:
        return None
    first, last = legs[0][0], legs[-1][1]
    if only is not None:
        legs = [(a, b) for a, b in legs if (a.path.name, b.path.name) == only]
        if not legs:
            raise KeyError(only)
    use_ai = ai_enabled() if ai is None else ai
    with _lock:
        row = store.find_project_batch(first.site)
        signature = _signature(*(hashes[m.path] for m in sorted(items, key=lambda m: m.order)))
        if row is None:
            batch_id = uuid.uuid4().hex[:12]
            store.create_batch(
                batch_id, site=first.key, project=first.site, name_a=first.path.name, name_b=last.path.name,
                tag_a=first.tag, tag_b=last.tag, path_a=str(first.path), path_b=str(last.path), signature=signature,
                ai_enabled=use_ai, criteria=batch_criteria(),
            )
            known: dict[str, dict] = {}
        else:
            batch_id = row["id"]
            known = {leg["signature"]: leg for leg in store.list_legs(batch_id)}
        added = False
        for a, b in legs:
            sig = _signature(hashes[a.path], hashes[b.path])
            leg = known.get(sig)
            if leg is None:
                store.add_leg(batch_id, tag_a=a.tag, tag_b=b.tag, name_a=a.path.name, name_b=b.path.name,
                              path_a=str(a.path), path_b=str(b.path), signature=sig)
                added = True
            elif leg["status"] == "error":
                store.update_leg(leg["id"], status="pending", error_message=None)
                added = True
        if row is None:
            return batch_id
        if not added:
            return None
        epochs = dict(site=first.key, name_a=first.path.name, name_b=last.path.name, tag_a=first.tag, tag_b=last.tag,
                      path_a=str(first.path), path_b=str(last.path), signature=signature)
        if row["status"] in ("done", "error"):
            store.update_batch(batch_id, status="queued", stage="queued", progress="", ai_enabled=int(use_ai),
                               criteria=batch_criteria(), **epochs)
            return batch_id
        store.update_batch(batch_id, **epochs)  # queued or running: the worker picks the new legs up itself
        return None


def queue_pair(items: list[MediaName], hashes: dict[Path, str], name_a: str, name_b: str) -> Optional[str]:
    """Batch one consecutive pair of a project by hand (see queue_project). Returns the project's batch id when it is
    queued and must be run, None when it is already running and picks the leg up itself."""
    queue_project(items, hashes, only=(name_a, name_b))
    row = store.find_project_batch(items[0].site)
    return row["id"] if row and row["status"] == "queued" else None


def rerun_batch(batch_id: str) -> str:
    """Queue the same sources (every leg) again with the current settings, e.g. AI switched on after a CV-only run."""
    row = store.get_batch(batch_id)
    if row is None:
        raise KeyError(batch_id)
    legs = store.list_legs(batch_id)
    for leg in legs:
        for key in ("path_a", "path_b"):
            if not Path(leg[key]).is_file():
                raise FileNotFoundError(f"Source file is gone: {Path(leg[key]).name}")
    new_id = uuid.uuid4().hex[:12]
    store.create_batch(new_id, **{k: row[k] for k in (
        "site", "project", "name_a", "name_b", "tag_a", "tag_b", "path_a", "path_b", "signature")},
        ai_enabled=ai_enabled(), criteria=batch_criteria())
    for leg in legs:
        store.add_leg(new_id, **{k: leg[k] for k in (
            "tag_a", "tag_b", "name_a", "name_b", "path_a", "path_b", "signature")})
    return new_id


def clear_queue() -> dict:
    """Flush every queued batch (see store.clear_queued) and its output folders; the files go back to the inbox
    as unbatched. Returns the deleted batch ids and the source files released."""
    with _lock:
        result = store.clear_queued()
    for batch_id in result["deleted"]:
        shutil.rmtree(BATCH_DIR / batch_id, ignore_errors=True)
    for batch_id, idx in result["dropped_pairs"]:
        shutil.rmtree(BATCH_DIR / batch_id / f"pair_{idx:02d}", ignore_errors=True)
    return {"deleted": result["deleted"], "files": result["files"]}


class BatchWorker:
    """Runs queued batches one at a time on a daemon thread, started on first use. While paused, the batch already
    running finishes and the next submitted one waits; a batch started by hand (run_now) runs anyway, first."""

    def __init__(self):
        self._auto: deque[str] = deque()
        self._manual: deque[str] = deque()
        self._cond = threading.Condition()
        self._thread: Optional[threading.Thread] = None
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        with self._cond:
            self._paused = True

    def resume(self) -> None:
        with self._cond:
            self._paused = False
            self._cond.notify_all()

    def submit(self, batch_id: str) -> None:
        with self._cond:
            self._auto.append(batch_id)
            self._start()

    def run_now(self, batch_id: str) -> None:
        """Run this batch next even while paused (a pair batched by hand with automatic batching off)."""
        with self._cond:
            if batch_id in self._auto:
                self._auto.remove(batch_id)
            if batch_id not in self._manual:
                self._manual.append(batch_id)
            self._start()

    def _start(self) -> None:  # with self._cond held
        self._cond.notify_all()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="batch-worker", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._manual or (self._auto and not self._paused))
                batch_id = (self._manual or self._auto).popleft()
            try:
                process_batch(batch_id)
            except Exception:
                log.exception("Batch worker failed on %s", batch_id)


worker = BatchWorker()


def sync_worker() -> None:
    """Pause or resume the worker to match the automatic-batching switch."""
    if auto_batch_enabled():
        worker.resume()
    else:
        worker.pause()


def resume_interrupted() -> list[str]:
    """Re-queue batches a previous process left queued or running."""
    ids = store.reset_interrupted()
    for batch_id in ids:
        worker.submit(batch_id)
    return ids
