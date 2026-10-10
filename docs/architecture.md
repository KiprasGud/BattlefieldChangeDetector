# Architecture

```
 Operator (React UI)
   │  image A (past), image B (present), criteria
   ▼
 FastAPI  POST /api/analyze            (main.py, pipeline.py)   [P3]
   │
   ├─0─ decode(A), decode(B) → pixels only (EXIF orientation, file name/type/size ignored)
   │
   ├─1─ align(A, B)  → B warped into A's frame + quality       (alignment/)  [P1]
   │      both images at a 1200 px working size → dense SIFT (also on mirrored B) → ratio test
   │      → MAGSAC homography → sanity check in a resolution-normalized frame → ECC fallback
   │
   ├─2─ change_heatmap(A*, B', mask) → heatmap image for the HEATMAP view only (diff/)  [P1]
   │      A* = A blurred to B's resolution when B is coarser (harmonize_resolution), else A
   │
   ├─3─ analyze(A, B', criteria, aligned) → AnalysisResult (analysis/)      [P2]
   │      criteria = presets.build_criteria(preset ids, free-text query): one written instruction block
   │      Gemini 3.5 Flash-Lite, IMINT prompt + few-shot, JSON-schema output, boxes 0-1000
   │      AI off: no detections (OpenCV only aligns), warning "AI step disabled"
   │
   └─4─ annotate(B', result) → red boxes                        (render/)     [P3]
   ▼
 UI: annotated image + change list + report + recommendation
```
Interfaces between stages are in `backend/app/contracts.py`. Each stage ships a stub so the full flow works from hour 0.

## Watch-folder batch pipeline (drone video and image pairs)
```
 input/Site_A_Day1.mp4 + input/Site_A_Day2.mov          (WATCH_DIR, default <repo>/input)
   │
   ├─0─ watcher: file settled (2 s quiet, size/mtime unchanged) → name grouping → project batch  (ingest/, batch.py)
   │      <key>_<Before|After|DayN>, extension ignored; all epochs of one key = one batch, one leg per
   │      consecutive step (Day1→Day2, Day2→Day5); a later epoch is appended to the same batch as a new leg
   │      same content pair (sha256 of both files) is never processed twice; finished legs keep their reviews
   │      AUTO_BATCH=0 / dashboard switch: files stay in the inbox unbatched, the worker pauses
   ├─1─ per leg, frames: still image = 1 frame; video → FFmpeg 0.5 fps, long side ≤ 1920, -noautorotate  (video/extract.py)
   ├─2─ frame matching (video/match.py): content only, never timestamps
   │      SIFT at 640 px → VLAD retrieval (top 4 B frames per A frame) → SIFT + MAGSAC homography check
   │      → footprint overlap ≥ 0.5 → best B frame per A frame → drop A frames repeating chosen ground
   │      → ≤ MATCH_MAX_PAIRS pairs, each scored by inliers, overlap and SSIM
   ├─3─ per pair: align() at full resolution (fallback: the verified matching homography)
   │      → change_heatmap with B's uncovered area filled by A's pixels → candidate boxes
   │      pairs without a candidate box are dropped (same ground, no difference)
   ├─4─ AI_ENABLED=1: analyze() (Gemini 3.5 Flash-Lite, heatmap boxes as hints, 4 review categories)
   │    AI_ENABLED=0, no key, MOCK_LLM=1 or Gemini error: heatmap boxes as "unknown_anomaly"
   └─5─ annotate + store pair and findings (SQLite, never auto-pruned) → review dashboard → report
```
- One batch runs at a time (worker thread): the CV work is CPU-bound; its legs run in order, and legs appended while
  it runs are picked up before it finishes. A restart re-queues unfinished batches (and their unfinished legs).
- Automatic batching can be stopped from the dashboard (`PUT /api/settings {"auto_batch": false}`): settled files
  stay in the inbox unbatched, and the worker finishes the batch it is running, then waits. While stopped,
  `POST /api/queue/clear` flushes the queue (a re-opened batch only loses its unfinished legs). Starting again
  batches every project waiting in the inbox and resumes the worker.
- Gemini cost per batch is bounded: ≤ 1920 px frames are never tiled, so ≤ 2 calls (detection + verification)
  per curated pair, ≤ 2 × `MATCH_MAX_PAIRS` per batch, and nothing for pairs without a CV difference.
- The heatmap code (`diff/heatmap.py`) is shared and unchanged. Only the batch path fills B's uncovered area with
  A's pixels before calling it, so partial-overlap frames do not light up along the coverage border
  (`pipeline.compute_heatmap(fill_uncovered=True)`); `/api/analyze` keeps the original input.
- Review categories: `missing_object`, `new_structure`, `terrain_change`, `unknown_anomaly`
  (labels in `contracts.CATEGORY_LABELS`). The reviewer accepts or rejects each finding; the report
  (`render/report.py`, JSON or self-contained HTML) lists accepted findings only.
- Limits: the homography models the ground plane, so tall objects keep some parallax (the AI verification pass and
  the reviewer filter it); overlays burned into the video image (OSD text) can cause false frame matches; a video is
  read up to 900 frames (30 min at 0.5 fps).

## Visual matching (stage 1)
Image B is matched to A by what is in the picture, never by file properties. It tolerates any resolution or aspect
ratio, zoom between 0.2x and 5x, any rotation, mirroring (horizontal, vertical, transposed) and crops down to
10% overlap, plus blur, brightness and JPEG artifacts (see `tests/test_alignment.py`).
- `ok=False` means "not the same scene": fewer than 25 inliers, inlier ratio below 0.15, implausible geometry or
  post-warp correlation below 0.2. Unrelated scenes measure 12-19 inliers; real matches 100+.
- `align_quality` = zero-normalized cross-correlation of A and warped B over their overlap (ECC correlation for the
  fallback): how visually similar the two images are after alignment.
- A homography with a negative determinant means B was mirrored; the pipeline warns about it.
- A result within half a pixel of an exact flip / 90° turn + whole-pixel shift is snapped to it, so already-aligned
  pairs, crops and rotated copies are copied pixel for pixel instead of being blurred by interpolation.
- The offline mock recognizes the demo pairs with the same matcher (`estimate_homography`) and maps fixture boxes
  into the uploaded frame.

## AI role and boundaries
Deterministic code, no AI: decoding, same-scene matching and registration, coverage mask, change heatmap and
candidate boxes, box validation (clamp, swap, drop thin or black-border boxes), sectors, report date, merging tile
results (NMS), rendering, cache, offline fallback.

Gemini (`gemini-3.5-flash-lite`, `backend/app/analysis/`) does exactly two things:
1. **Detection**: compares A with aligned B against the operator's criteria, returns typed changes with boxes, a
   2-sentence summary and a recommendation. Pre-made target classes (`analysis/presets.py`) and the free-text
   query reach the model as one criteria block. Only the batch path passes heatmap candidates as hints; the
   single-pair `/api/analyze` flow sends none, so every detection there is the model's own.
2. **Verification** (`ANALYSIS_VERIFY=1`): sees A/B crops of each detection and rejects shadows, lighting,
   alignment artifacts and off-criteria changes. A failed verification keeps the detections.

Gemini never decides whether two images match, never sees file metadata (images are re-encoded from pixels as
JPEG), and never receives earlier jobs.

| Setting | Value |
|---|---|
| Model | `GEMINI_MODEL`, default `gemini-3.5-flash-lite` (generateContent; stateless, nothing stored server-side) |
| Thinking | `GEMINI_THINKING_LEVEL`, default `minimal` |
| Image detail | full images `high` (1120 tokens each), verification crops `medium` |
| Sampling | no `temperature` on Gemini 3 (deprecated); legacy `gemini-2*` keep 0.2 / 0.0 |
| Calls per analysis | ≤ 2000 px: 1 detection + 1 verification. Larger: 1 full + 16 tiles + 1 verification. Cache hit or offline: 0 |
| Failures | 408/429/5xx, network and malformed JSON: 3 attempts. Other 4xx (bad key, unknown model): fail fast. Then the pipeline switches to fixtures with an OFFLINE MODE warning naming the error |
