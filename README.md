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
| P1 Alignment | `backend/app/alignment/` |
| P2 AI analysis | `backend/app/analysis/` |
| P3 API/UI/integration | `backend/app/{main,pipeline}.py`, `backend/app/render/`, `frontend/`, `docs/` |
| Shared (PR only) | `backend/app/contracts.py`, `frontend/src/types.ts` |

## Merge plan
1. **H0**: this scaffold on `main` — every stage is a working stub, so end-to-end works immediately with fixture data.
2. Each person branches (`feat/alignment`, `feat/analysis`, `feat/api-ui`), replaces their stub behind the same interface, merges small and often.
3. **Checkpoint 1 (~H2)**: first real versions merged; app still runs end-to-end.
4. **Checkpoint 2 (~H4)**: joint integration run with a real pair (align → Gemini → boxes in UI); fix contract mismatches (box order, image sizes) in one agreed PR.
5. **Polish** until feature freeze 1h before demo; last hour = rehearsal with 2 prepared pairs and `MOCK_LLM=1` fallback.

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

