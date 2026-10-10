# Round 1 review (state of `main` at `349d3c2`)

Tests: `cd backend && pytest` → **19 passed**. Each problem below is assigned to its owner in [`team.md`](team.md) (Phase 2).

## What changed in round 1
| Owner | Files | What |
|---|---|---|
| P2 | `backend/app/analysis/*` | Gemini call with JSON response schema, 3 attempts, box cleanup (clamp/swap/drop), 4×4 sector, Lithuanian confidence mapping, lt/en prompt with few-shot examples, CLI for manual runs, 7 tests |
| P1 | `alignment/register.py`, `tests/test_alignment.py` | CLAHE brightness normalization, SIFT + ratio test + RANSAC homography, ECC fallback, border mask after warp, debug A/B overlay, synthetic-shift test |
| P3 | `main.py`, `pipeline.py`, `render/annotate.py`, `frontend/*`, docs, samples | Input validation (empty criteria, language, 25 MB → 413), `/api/samples` + sample file route, `image_a_url` in response, HUD-style boxes + 4×4 grid overlay, full dark UI (demo pair buttons, preset chips, EN/LT, slider / annotated / side-by-side views, clickable boxes ↔ report, JSON and image export), 2 synthetic 800×600 sample pairs |

## Current problems (ranked)

### Demo-breaking
1. **Mock boxes don't match the sample images.** `MOCK_LLM=1` is the default and the demo fallback. It always returns the same single fixture, so boxes land on empty grass in pair01/pair02, and criteria and language are ignored. → **P2**
2. **Real Gemini has never run end-to-end.** No API key has been used yet. Prompt quality, box accuracy and the default model `gemini-2.5-flash` are unverified. → **P2**
3. **Sample pairs are already aligned.** Measured homography ≈ identity, quality 0.98. The jury never sees alignment do anything, so the "loitering orbit / oblique angle" pitch is not demonstrated. → **P1**
4. **The API blocks the whole server.** `async def analyze_endpoint` calls the synchronous `pipeline.run` (Gemini can take up to 3 × 60 s). Every other request waits. → **P3**

### Correctness / robustness
5. **Contract drift.** `frontend/src/types.ts` has no `image_a_url`. The backend sends it and `ResultViewer.tsx` casts around it. → **P3** (contract PR)
6. **Alignment says "ok" too easily.** `ok` only needs inlier ratio ≥ 0.1. No sanity check on the homography (determinant, scale, skew), so bad warps are reported as aligned. ECC sets a fake constant quality of 0.5, and fails silently when A and B differ in size. → **P1**
7. **Black warp borders** are sent to Gemini and shown to the operator. Possible false positives. → **P1** (mask) + **P2** (ignore masked area)
8. **No accuracy measurement.** Nobody knows the precision/recall of detections. → **P2**
9. **`backend/output/` grows forever.** No cleanup, and outputs are not linked to any history. → **P3**
10. **CORS config is invalid.** `allow_origins=["*"]` together with `allow_credentials=True` is rejected by browsers. Harmless behind the Vite proxy, breaks direct calls. → **P3**
11. **Setup depends on the person's machine.** On at least one laptop Node is not installed and Python is not on PATH. The frontend was not built there. → **P3**

### Missing from the original brief
12. No change **heatmap** (brief: "Heatmap/Bounding boxes"). → **P1**
13. No 4×4 **tiling** for small objects (cables, tracks) on large images. → **P2**
14. Report is JSON only. No operator-friendly text/PDF report, no mission history. → **P3**
15. Round 1 checklists for P1/P2 were never ticked, so status was unclear. → everyone ticks their boxes in `team.md` from now on.
