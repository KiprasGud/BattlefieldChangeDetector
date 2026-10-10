# Team instructions — Phase 2 (3 people, ~12 h)

Round 1 is done and merged (see [`review.md`](review.md) for what changed and the numbered problems `#1`–`#15` referenced below).

**Golden rules**
1. Only edit files in YOUR directories (table below). `backend/app/contracts.py` and `frontend/src/types.ts` are shared: change only via a small agreed PR + message to the team.
2. Never break `main`. Before merging: `cd backend && pytest` green, `cd frontend && npm run build` green, 2-minute smoke run on every sample pair with `MOCK_LLM=1`.
3. Keep every new parameter a working no-op until your side lands (e.g. `hints` ignored, `heatmap_url` absent). Never commit `.env` / API keys.
4. Branches: `p1/align-v2`, `p2/eval`, `p3/jobs-ui` (plus short feature branches). Rebase on `main` often, merge small and often.
5. Box convention: `[ymin, xmin, ymax, xmax]`, 0–1000, origin top-left of image A.
6. Tick your boxes (`- [x]`) in this file when a task is merged.

| Person | Owns |
|---|---|
| P1 Vision | `backend/app/alignment/`, `backend/app/diff/` (new), `tools/` (new), `backend/tests/test_alignment.py`, `backend/tests/test_diff.py` |
| P2 AI + eval | `backend/app/analysis/`, `eval/` (new), `shared/fixtures/`, `backend/tests/test_analysis.py` |
| P3 API/UX/ops | `backend/app/{main,pipeline}.py`, `backend/app/render/`, `backend/app/storage/` (new), `frontend/`, `docs/`, `README.md`, `backend/tests/test_api.py` |
| Shared (PR only) | `backend/app/contracts.py`, `frontend/src/types.ts` |

Setup: `cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt` · `copy .env.example .env` · `cd frontend && npm i`.
Run: `cd backend && uvicorn app.main:app --reload` and `cd frontend && npm run dev`.

---
## M0 — contract PR (first 45 min, P3 opens, P1 + P2 approve)
- [ ] `contracts.py`: `AlignResult.method: "sift" | "ecc" | "none"`, `AlignResult.valid_mask: Optional[ndarray]` (255 = real pixels of B after warp).
- [ ] `contracts.py`: `AnalyzeResponse.images` may contain `heatmap_url`; `AnalyzeResponse` gains `timings: dict[str, float]` and `warnings: list[str]` (both with defaults).
- [ ] New `analyze(img_a, aligned_b, criteria, lang, hints: list[list[int]] | None = None)`; `hints` = candidate boxes (0–1000) from the heatmap.
- [ ] `types.ts` mirrors all of it, including the missing `image_a_url` (#5).
While M0 is open, P1/P2 start on the M1 tasks that don't depend on it.

---
## Person 1 — Vision: alignment + change heatmap
Goal: reliable alignment on oblique shots, plus a pixel-level change heatmap that tells the AI where to look.

**M1 (0–3 h) — fix alignment (#6, #7)**
- [ ] Match on a downscaled copy (long side ≤ 1600 px), then scale the homography back to full size.
- [ ] Sanity-check H: determinant > 0, scale 0.5–2, small perspective terms; reject otherwise.
- [ ] `ok` only when inliers ≥ 30 **and** inlier ratio ≥ 0.3.
- [ ] ECC: resize B to A's size first; quality = ECC correlation coefficient (not a constant).
- [ ] Return `method` and `valid_mask`.
- [ ] Tests: rotated 10°, scaled 0.9, perspective-warped, brightness-shifted pairs; degenerate input (blank image) → `ok=False`, never raises.

**M2 (3–6 h) — change heatmap (#12)**
- [ ] `backend/app/diff/heatmap.py`: `change_heatmap(img_a, aligned_b, valid_mask) -> float32 0–1 map` (Lab colour difference + gradient difference, shadow suppression for pure-luminance drops, morphological cleanup, Gaussian blur, masked area = 0).
- [ ] `candidate_boxes(heatmap, top_n=10) -> list[[ymin,xmin,ymax,xmax]]` in 0–1000.
- [ ] `backend/tests/test_diff.py`: a drawn circle/line in B is found; identical images give no boxes.

**M3 (6–9 h) — oblique demo pairs (#3)**
- [ ] `tools/make_oblique_pair.py`: warp existing samples with perspective + rotation + lighting change → `shared/sample_data/pair03`, `pair04`.
- [ ] Find 1–2 real public aerial before/after pairs (note the license in `shared/sample_data/README.md`).
- [ ] Give P2 the true change locations for every new pair (for labels).

**M4 (9–12 h) — performance and support**
- [ ] Alignment + heatmap ≤ 1 s on 4000×3000.
- [ ] Debug overlay written per job when `DEBUG_ALIGN=1`.
- [ ] Help P2 with tiling geometry (tile ↔ full-image box mapping).
Do not touch: analysis, API, UI.

---
## Person 2 — AI analysis + evaluation
Goal: detections that are measurably good, a demo that never depends on the network.

**M1 (0–3 h) — make the demo honest (#1, #2)**
- [ ] Per-sample mock fixtures `shared/fixtures/pair01.json`, `pair02.json` (boxes on the real changes), selected by image hash; filter by criteria; Lithuanian text for `lang=lt`. Unknown images → generic fixture.
- [ ] Get an API key and run real Gemini on every sample pair with `python -m app.analysis.cli`.
- [ ] Compare 2 models (latency + quality); set the default in `GEMINI_MODEL` / `.env.example`.
- [ ] Ignore the masked (black) area: tell the model in the prompt (#7).

**M2 (3–6 h) — use the heatmap**
- [ ] When `hints` are given, list them in the prompt ("verify or reject each candidate region").
- [ ] Optionally send the heatmap as a third image.
- [ ] Verification pass: re-check each reported box, drop rejected ones.

**M3 (6–9 h) — evaluation harness (#8)**
- [ ] `eval/labels/<pair>.json`: ground-truth boxes per criteria for 4+ pairs (with P1's new pairs).
- [ ] `python -m eval.run` → precision / recall / mean IoU per pair and per config (hints on/off, tiling on/off, model) → `eval/results.md`.
- [ ] Tune prompt and confidence threshold with it.

**M4 (9–12 h) — tiling + caching (#13)**
- [ ] 4×4 tiles with overlap for images > 2000 px; map tile boxes back; merge with NMS.
- [ ] Cache results by (image hashes, criteria, lang, model) to save quota during the demo.
Do not touch: OpenCV alignment, API, UI.

---
## Person 3 — API, UX, reporting, ops
Goal: a responsive app with history and real reports, startable with one command.

**M0** — contract PR above; fix CORS (#10).

**M1 (0–3 h) — stop blocking the server (#4)**
- [ ] Job model: `POST /api/analyze` → `{job_id}`; `GET /api/jobs/{id}` → stage (`aligning` → `heatmap` → `ai` → `render` → `done`/`error`) and the result. Run work in a background thread.
- [ ] UI progress bar driven by real stages; show `timings`.
- [ ] Update `docs/api.md` + `test_api.py`.

**M2 (3–6 h) — integrate the heatmap**
- [ ] Pipeline: compute heatmap (P1), save `heatmap.png`, pass `candidate_boxes` as `hints` (P2), collect `warnings`.
- [ ] UI: heatmap overlay toggle with opacity slider; show alignment method, quality and warnings.

**M3 (6–9 h) — history and reports (#9, #14)**
- [ ] `backend/app/storage/`: SQLite job history (inputs, result, timings); `GET /api/jobs` list; reopen past jobs in the UI.
- [ ] Output cleanup: keep the last 50 jobs / 24 h.
- [ ] Operator report: printable page / PDF export (annotated image, sector table, summary, recommendation) in EN and LT.

**M4 (9–12 h) — ops and demo (#11)**
- [ ] One-command start: `start.ps1` (finds Python/Node, installs, runs both) and/or `docker compose up`.
- [ ] Gemini failure → automatic mock with a visible "OFFLINE MODE" banner.
- [ ] Demo script using the oblique pairs; final rehearsal.
Do not touch: alignment/analysis internals (ask the owner).

---
## Merge plan / sync points
| When | Who | What must be on `main` |
|---|---|---|
| 0:45 (M0) | all | Contract PR merged; new params are no-ops; everything still green |
| ~3 h (M1 sync) | all | Fixes for #1–#7 merged — demo is already safe with `MOCK_LLM=1` |
| ~6 h (M2 sync, call) | all | Heatmap → hints → Gemini → UI overlay end-to-end on a real pair; fix box/heatmap orientation issues together |
| ~9 h (M3 sync) | all | Eval numbers reviewed; final config chosen (model, hints on/off, tiling threshold) and frozen |
| 11 h | all | Feature freeze — bug fixes only |
| 11–12 h | all | Rehearsal, including offline fallback |
