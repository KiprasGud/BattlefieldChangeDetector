# Team instructions (3 people, parallel)

**Golden rules**
1. Only edit files in YOUR directories. `backend/app/contracts.py` and `frontend/src/types.ts` are shared: change only via a tiny PR + message to the team.
2. Never break `main`. Before merging run: `cd backend && pytest` and a quick `uvicorn` + UI smoke test.
3. Keep stubs working until your real version is ready. Never commit `.env` / API keys.
4. Branch names: `feat/alignment` (P1), `feat/analysis` (P2), `feat/api-ui` (P3). Rebase on `main` often, merge small and often.
5. Box convention: `[ymin, xmin, ymax, xmax]`, 0–1000, origin top-left of image A.

Setup: `cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt` · `copy .env.example .env` · `cd frontend && npm i`.
Run: `cd backend && uvicorn app.main:app --reload` and `cd frontend && npm run dev` (UI proxies `/api` to :8000).

---
## Person 1 — Alignment (`backend/app/alignment/`, `backend/tests/test_alignment.py`)
Goal: `align(img_a, img_b) -> AlignResult` warps B onto A.
- [ ] SIFT (or ORB) features + Lowe ratio test, `cv2.findHomography(RANSAC)`, `cv2.warpPerspective` into A's size. `quality` = inlier ratio.
- [ ] Fallback: ECC (`cv2.findTransformECC`) if too few matches; `ok=False` when quality below threshold (don't raise).
- [ ] Brightness/histogram normalization to reduce shadow differences; crop/mask black borders after warp.
- [ ] Test with `shared/sample_data/*` plus a synthetic rotated/shifted copy (residual after align should be small).
- [ ] Debug helper that writes an A/B blend overlay.
Do not touch: analysis, API, UI.

## Person 2 — AI analysis (`backend/app/analysis/`, `backend/tests/test_analysis.py`)
Goal: `analyze(img_a, aligned_b, criteria, lang) -> AnalysisResult` using Gemini.
- [ ] `gemini_client.py`: send both images + `prompts.build_prompt(...)`, structured JSON output (response schema = `AnalysisResult`), low temperature, timeout + retries.
- [ ] Validate via Pydantic; clamp/drop invalid boxes; fill `sector` from box center (4x4 grid A–D × 1–4).
- [ ] Tune `prompts.py`: IMINT role, 4-step workflow, few-shot examples (tracks, craters, trees, cables), false-positive rejection, `lt`/`en` report language.
- [ ] If recall is poor: analyze 4x4 tiles and merge/dedupe boxes.
- [ ] Keep `MOCK_LLM=1` fixture path working so teammates never burn quota.
Do not touch: OpenCV alignment, API, UI.

## Person 3 — API, rendering, UI, integration (`backend/app/{main,pipeline}.py`, `backend/app/render/`, `frontend/`, `docs/`, `README.md`)
Goal: the demo experience + gluing it together.
- [x] Keep `/api/analyze` per `docs/api.md`; error handling, upload size limits, `GET /api/samples` for demo pairs.
- [x] `render/annotate.py`: nicer red boxes, numbered labels, optional 4x4 sector grid.
- [x] UI: preset chips + free-text criteria, loading state, annotated image, change list that highlights its box on click, confidence badges, alignment warning, copy/export report JSON, before/after slider.
- [x] Owns merge/integration (see `README.md` plan), demo script and fallback (`MOCK_LLM=1`) rehearsal.
Do not touch: alignment/analysis internals (ask the owner).
