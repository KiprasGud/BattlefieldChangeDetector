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
   ├─2─ change_heatmap(A*, B', mask) → heatmap + candidate boxes (diff/)      [P1]
   │      A* = A blurred to B's resolution when B is coarser (harmonize_resolution), else A
   │
   ├─3─ analyze(A, B', criteria, hints, aligned) → AnalysisResult (analysis/) [P2]
   │      Gemini 3.5 Flash-Lite, IMINT prompt + few-shot, JSON-schema output, boxes 0-1000
   │
   └─4─ annotate(B', result) → red boxes                        (render/)     [P3]
   ▼
 UI: annotated image + change list + report + recommendation
```
Interfaces between stages are in `backend/app/contracts.py`. Each stage ships a stub so the full flow works from hour 0.

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
   2-sentence summary and a recommendation. Heatmap candidates are passed as hints to confirm or reject.
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
