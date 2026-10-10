# Žvalgas AI — battlefield change detection

Operator uploads "before" and "after" drone photos + criteria (e.g. "new vehicle tracks, craters"). The system aligns the images (OpenCV), asks a vision LLM (Gemini) for changes matching the criteria, draws red boxes and produces a report.

See `docs/architecture.md`, `docs/api.md`, and **`docs/team.md`** (instructions for the 3 people).

## Quick start
```
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # add GEMINI_API_KEY; MOCK_LLM=1 uses the fixture
uvicorn app.main:app --reload

cd frontend
npm i && npm run dev        # http://localhost:5173
```
Tests: `cd backend && pytest`.

## Ownership (no overlap = no merge conflicts)
| Person | Directories |
|---|---|
| P1 Vision | `backend/app/alignment/`, `backend/app/diff/`, `tools/` |
| P2 AI + eval | `backend/app/analysis/`, `eval/`, `shared/fixtures/` |
| P3 API/UX/ops | `backend/app/{main,pipeline}.py`, `backend/app/render/`, `backend/app/storage/`, `frontend/`, `docs/` |
| Shared (PR only) | `backend/app/contracts.py`, `frontend/src/types.ts` |

## Status and merge plan
Round 1 (scaffold → alignment, Gemini analysis, API/UI) is merged. Review and open problems: `docs/review.md`.

Phase 2 (~12 h) is in `docs/team.md`:
1. **M0 (0:45)**: one contract PR (alignment method/mask, heatmap URL, timings, warnings, `hints`); new params are no-ops until used.
2. **M1 (~3 h)**: demo-breaking fixes merged (matching mock fixtures, real Gemini run, non-blocking API, stricter alignment).
3. **M2 (~6 h)**: change heatmap → hints → Gemini → UI overlay, end-to-end.
4. **M3 (~9 h)**: evaluation numbers reviewed, final config frozen; history + operator reports.
5. **M4 (~12 h)**: tiling, one-command start, offline mode; feature freeze at 11 h, last hour = rehearsal.

## Demo Script & Fallback Rehearsal
1. **Start Services**:
   - Backend: `cd backend && uvicorn app.main:app --reload`
   - Frontend: `cd frontend && npm run dev` (opens `http://localhost:5173`)
2. **Rehearsal with Fallback (`MOCK_LLM=1`)**:
   - In `backend/.env`, set `MOCK_LLM=1` to guarantee instant responses without external API latency or quota limits.
3. **Demo Flow**:
   - Click **Sample 01 - Treeline & Roadway** in the top demo bar to instantly populate Image A & Image B.
   - Click preset chips (e.g., `+ New vehicle tracks`, `+ Craters / digging`).
   - Click **Execute Change Detection**.
   - Use the **Before/After Slider** to interactively sweep between baseline and recon imagery.
   - Click change items in the tactical report to inspect target boxes directly in the HUD.
   - Click **Copy Report JSON** or **Download JSON** for operator export.

