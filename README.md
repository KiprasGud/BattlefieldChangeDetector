# Žvalgas AI — Battlefield Change Detector

Žvalgas AI compares a **past** (baseline) and a **present** (recon) aerial drone image of the same sector and reports
what changed: craters, trenches, new wires, vehicle tracks, camouflaged positions, structural damage, and anything
else the operator asks for in plain language. It runs as a keyboard-first operator terminal (React) on top of a
FastAPI backend.

**Core principle: OpenCV aligns, AI detects.** Deterministic computer vision only decodes, matches and geometrically
registers the two images (and draws a heatmap as a visual aid). Every detection, whether from a pre-made target class
or a free-text query, is made by the same multimodal AI pathway (Gemini), which generalizes across lighting, scale,
angle and resolution.

---

## Features

- **Single-pair change detection.** Drop two images, pick target classes and/or type a query, press `F5`.
- **8 AI target classes, freely combinable with a custom query.** Wires/tripwires, craters, trenches/foxholes, vehicle
  tracks, camouflage netting, structural damage, vehicles, felled trees. Each class is expanded server-side into a
  written visual instruction for the model, not a template match.
- **Robust visual matching.** Image B is registered to A by content alone. It tolerates any resolution or aspect
  ratio, 0.2×–5× zoom, any rotation, mirroring and crops down to ~10 % overlap, plus blur, brightness changes and JPEG
  artifacts. EXIF data, file names and dates are ignored.
- **Two-pass AI.** Detection is followed by a verification pass on A/B crops that rejects shadows, lighting
  differences, alignment artifacts and off-criteria changes. Large images are analyzed in overlapping tiles.
- **Diff viewer.** Wipe slider, HUD (annotated), side-by-side split and heatmap overlay, with clickable target boxes.
- **Telemetry pane.** UTC system log (stages, backend warnings, errors), coordinate readout, and Cursor-on-Target
  (CoT) XML and JSON export with an inline payload inspector.
- **Watch-folder batch review.** Drop drone videos or image pairs into `input/`. Frames are extracted, matched by
  content, aligned and analyzed. A review dashboard lets you accept or reject findings and export a verified report.
- **Offline mode.** With `MOCK_LLM=1` (the default) or no API key, recorded fixtures stand in for Gemini, so the full
  flow works without a network.
- **Analysis cache.** Identical requests are served from disk to save quota.
- **Reports in English or Lithuanian** (`lang=en|lt`).
- **UI.md design system.** A 3-pane, high-density terminal with dark, light and NVG themes and a visible shortcut on
  every control.

---

## Architecture

### Single-pair pipeline (`POST /api/analyze`)

```
 Operator terminal (React)
   │ image A (past), image B (present), presets=craters,wires, criteria="free text"
   ▼
 FastAPI main.py ── presets.build_criteria() → one written criteria block
   │ job queued (SQLite), worker thread runs pipeline.run()
   ▼
 0  decode            pixels only (EXIF orientation, names, sizes ignored)
 1  align             alignment/   SIFT (also on mirrored B) → ratio test → MAGSAC homography
                                   → sanity checks → ECC fallback → B warped into A's frame + valid mask
 2  heatmap           diff/        change heatmap image, for the HEATMAP view only (never sent to the AI)
 3  analyze           analysis/    Gemini detection (A + aligned B + criteria, JSON schema)
                                   → verification pass on crops → boxes cleaned, sectors assigned
                                   (offline: fixture mock; AI off: no detections + warning)
 4  annotate          render/      boxes + optional 4×4 grid burned into annotated.jpg
   ▼
 job result: changes[], summary, recommendation, align quality, images, timings, warnings
```

### Watch-folder batch pipeline

```
 input/Site_A_Day1.mp4 + input/Site_A_Day2.mov       (name pairing <key>_<Before|After|DayN>)
   → ingest/watcher   file settled → pair → batch row (same content never processed twice)
   → video/extract    FFmpeg, 0.5 fps, long side ≤ 1920 px (a still image = 1 frame)
   → video/match      SIFT + VLAD retrieval + homography check → best B frame per A frame (content, not time)
   → per pair         align → heatmap (pairs with no difference are dropped)
                      → Gemini analysis (AI on) or heatmap regions as unknown anomalies (AI off)
   → storage/batches  pairs + findings (SQLite) → review dashboard → render/report (HTML/JSON)
```

The batch path still uses the heatmap to decide which frame pairs are worth sending to the AI, and passes its regions
as hints. Full details: [`docs/architecture.md`](docs/architecture.md).

### Module map

| Path | Responsibility |
|---|---|
| `backend/app/main.py` | FastAPI app: analyze jobs, presets, samples, job history, settings, batch/review API, static files |
| `backend/app/pipeline.py` | Single-pair orchestration: decode → align → heatmap → analyze → annotate |
| `backend/app/batch.py` | Batch worker for watch-folder pairs (frames, matching, per-pair analysis) |
| `backend/app/contracts.py` | Frozen Pydantic contracts (`Change`, `AnalysisResult`, `AlignResult`, `AnalyzeResponse`) |
| `backend/app/alignment/` | Feature extraction, homography estimation, ECC fallback, resolution harmonization |
| `backend/app/diff/heatmap.py` | Change heatmap + candidate boxes (shared; treated as frozen) |
| `backend/app/analysis/gemini_client.py` | Gemini calls: JSON schema output, retries, verification pass |
| `backend/app/analysis/prompts.py` | IMINT system prompt, few-shot examples, verification prompt (`PROMPT_VERSION`) |
| `backend/app/analysis/presets.py` | The 8 target classes and `build_criteria` / `split_criteria` |
| `backend/app/analysis/mock.py` | Offline fixtures: recognizes the demo pairs visually, filters by target class |
| `backend/app/analysis/tiling.py`, `cache.py`, `postprocess.py` | Tiled analysis + NMS, on-disk cache, box cleaning and sectors |
| `backend/app/video/`, `ingest/` | FFmpeg frame extraction, frame matching, folder watcher and name pairing |
| `backend/app/render/` | Annotated image and verified-findings report |
| `backend/app/storage/` | SQLite jobs (pruned to 50 / 24 h) and batches (kept) |
| `frontend/src/App.tsx` | Analyze view: 3-pane terminal, presets, shortcuts, themes, exports |
| `frontend/src/components/ResultViewer.tsx` | Slider / HUD / split / heatmap views with box overlay |
| `frontend/src/components/ReviewDashboard.tsx` | Batch queue, pair navigator, findings triage, report export |
| `frontend/src/api.ts`, `types.ts` | API client (job submit + polling) and shared types |
| `frontend/src/index.css` | Design tokens and styles implementing `UI.md` |

---

## AI detection pathway

Pre-made target classes and the custom query go through **one** code path. The frontend sends the selected class ids
plus the query text. `presets.build_criteria()` joins each selected class's label and the query into one plain-text
query, exactly as if the operator had typed it. That text is inserted into the Gemini system prompt and reused by
the verification pass:

```
Craters / Artillery Impacts, New Wires / Tripwires / Comms Lines, destroyed artillery near the treeline
```

A query on its own is passed through unchanged.

| Key | Id | Target class | Review category |
|---|---|---|---|
| `Alt+1` | `wires` | New Wires / Tripwires / Comms Lines | unknown_anomaly |
| `Alt+2` | `craters` | Craters / Artillery Impacts | terrain_change |
| `Alt+3` | `trenches` | Trenches / Foxholes / Earthworks | terrain_change (revetted: new_structure) |
| `Alt+4` | `tracks` | Vehicle Tracks / Heavy Equipment | terrain_change |
| `Alt+5` | `camouflage` | Camouflage Netting / Concealed Positions | new_structure |
| `Alt+6` | `damage` | Structural Damage / Rubble | unknown_anomaly |
| `Alt+7` | `vehicles` | Vehicles / Equipment | unknown_anomaly / missing_object |
| `Alt+8` | `felled_trees` | Felled Trees / Clearing | terrain_change |

**Model output** (validated JSON schema): per change `type`, `category` (`missing_object`, `new_structure`,
`terrain_change`, `unknown_anomaly`), `description`, `location_text`, `confidence` (`high|medium|low`) and `box` =
`[ymin, xmin, ymax, xmax]` normalized to 0–1000 in image A's frame. It also returns a 2-sentence `summary` and a
`recommendation`. The backend clamps and validates boxes, drops boxes on black borders and assigns 4×4 grid sectors
(`A1`–`D4`).

**Runtime behaviour**
- Model: `gemini-3.5-flash-lite` (`GEMINI_MODEL`). Images are re-encoded from pixels, so no metadata reaches the
  model, and every call is stateless.
- Calls: images ≤ 2000 px take 1 detection + 1 verification call. Larger images take 1 full pass + a 4×4 grid of
  overlapping tiles + 1 verification call.
- Errors: 408/429/5xx and malformed JSON are retried 3 times. Any other failure switches the job to fixture data with
  an `OFFLINE MODE` warning shown in the log.
- AI off (`AI_ENABLED=0` or the review-dashboard toggle): `/api/analyze` returns **no detections**, plus the warning
  *"AI step disabled: OpenCV is used for alignment only"*. OpenCV never produces detections in this flow.
- The prompt version is part of the cache key, so editing a prompt invalidates earlier cached answers.

---

## Operator terminal (UI.md)

The UI follows [`UI.md`](UI.md) exactly. It is a fixed 3-pane grid:

| Pane | Width | Contents |
|---|---|---|
| Ingestion & Parameters | 25 % | Baseline/Recon dropzones, target-class toggles, custom query, EXECUTE |
| Diff Engine | 55 % | Idle wireframe, processing state, or the result viewer (slider / HUD / split / heatmap) |
| Telemetry & Output | 20 % | Theme switches, coordinate readout, system log, CoT XML / JSON export + inspector |

**Design rules applied**
- No radius, shadows, transitions or gradients.
- 1 px borders.
- 12 px (`0.75rem`) minimum data size.
- Monospace (JetBrains Mono) for numbers, logs and coordinates; Inter for labels.
- Hover states are a 1 px outline or inverted colours only.

**Themes**
- **Dark** (default): `#111827` background, `#374151` borders, `#F9FAFB` text.
- **Light** (`Alt+S`): `#E5E7EB` background, `#9CA3AF` borders, `#000000` text.
- **NVG** (`Alt+N`): green on black.
- Accents in every theme are limited to `#EF4444` (errors and targets) and `#10B981` (success and alignment).

### Keyboard reference

| Analyze view | | Review view (`#review`) | |
|---|---|---|---|
| `F5` / `Ctrl+Enter` | Execute | `←` / `→` | Previous / next pair |
| `Alt+1`…`Alt+8` | Toggle target class | `↑` / `↓` | Previous / next finding |
| `/` | Focus custom query | `A` / `R` / `U` | Accept / reject / reset finding |
| `Alt+B` / `Alt+C` | Open baseline / recon picker | `E` / `J` / `P` | Export report HTML / JSON / PDF |
| `1` `2` `3` `4` | Slider / HUD / split / heatmap | `Alt+↑` / `Alt+↓` | Previous / next batch |
| `Alt+X` / `Alt+J` | Export CoT XML / JSON | `Alt+Q` | Re-run batch |
| `Alt+I` | Toggle payload inspector | `Alt+I` | Toggle AI step |
| `Esc` `Esc` (within 1 s) | Purge buffers | `1` `2` `3` `4` | Viewer mode |
| `Alt+A` / `Alt+R` | Analyze / Review view | `Alt+A` / `Alt+R` | Analyze / Review view |
| `Alt+S` / `Alt+N` | Light ↔ dark / NVG | `Alt+S` / `Alt+N` | Light ↔ dark / NVG |
| `↑` / `↓` | Previous / next target | `V` | View report |

In the slider view, the divider also takes `←`/`→` (`Shift` for bigger steps), `Home` and `End` when focused.

### Exports
- **CoT XML**: one `<event>` per target (`TRGT-01`…). The type is `a-h-G-U-C` when the `vehicles` or `tracks` class
  was searched, `a-h-G` otherwise. Each event carries the target's AI label and box bounds in its remarks. There is
  no GPS in the imagery, so points are `0,0`, `ce=9999`.
- **JSON**: job id, timestamp, and per target its id, AI label and box.

Every target carries a unique descriptive AI label (`type`, e.g. "large crater, road edge" / "small crater, north
field"). It is shown on the box overlay, burned into the annotated image and listed in the right pane.

---

## HTTP API

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness |
| `GET /api/presets` | Target classes `[{id, label, shortcut}]` |
| `POST /api/analyze` | multipart: `image_a`, `image_b`, `presets` (comma ids), `criteria` (free text), `lang` (`en`/`lt`), `draw_grid`; `?sync=true` to block. Needs at least one of `presets`/`criteria`. Max 25 MB per image |
| `GET /api/jobs/{id}` · `GET /api/jobs` | Job status/stage/timings/result · recent history |
| `GET /api/samples` · `GET /api/samples/{pair}/{file}` | Demo pairs in `shared/sample_data` |
| `GET` / `PUT /api/settings` | AI toggle, watch folder, frame rate, pair cap |
| `GET /api/inbox` | Watch-folder files waiting for a partner or rejected by name |
| `GET /api/batches` · `GET /api/batches/{id}` · `POST /api/batches/{id}/rerun` | Batch queue, detail, re-run |
| `POST /api/findings/{id}/review` | `{"status": "accepted" \| "rejected" \| "pending"}` |
| `GET /api/batches/{id}/report?format=json\|html` | Verified-findings report download |
| `GET /api/files/{job}/{file}` | Result images (`image_a`, `aligned_b`, `heatmap`, `annotated`) |

Interactive docs are served at `http://localhost:8000/docs`. Contract details: [`docs/api.md`](docs/api.md).

---

## Watch-folder batch review

1. **Drop** two files named `<key>_<Before|After|DayN>` into `input/` (or `WATCH_DIR`), e.g. `Site_A_Day1.mp4` +
   `Site_A_Day2.mov` or `ProjectX_Before.jpg` + `ProjectX_After.png`.
   - Extensions, EXIF, file sizes and dates are ignored; image vs video is read from the file content.
   - `Day1`, `Day2`, `Day3` pair consecutively.
2. **Processing** is automatic, one batch at a time:
   - FFmpeg (bundled via `imageio-ffmpeg`) extracts 1 frame every 2 s.
   - Frames of the two flights are matched by content, not time.
   - Each pair is aligned and diffed.
   - Pairs without a difference are dropped.
3. **AI step** (`AI_ENABLED`, or `Alt+I` in the dashboard): ON sends the curated pairs to Gemini with
   `BATCH_CRITERIA` (default: any real physical change). OFF keeps the heatmap regions as unclassified findings.
4. **Review** at `http://localhost:5173/#review`:
   - each pair can be viewed as slider, split or heatmap;
   - findings are grouped by category and accepted or rejected one by one;
   - export the verified report (HTML or JSON, accepted findings only).

Headless alternative: `cd backend && python -m app.ingest.watcher [FOLDER] [--once]`. Set `WATCH_ENABLED=0` for the
API in that case.

---

## Configuration

Copy [`.env.example`](.env.example) to `.env` in the repository root (or `backend/`) and adjust it.

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | – | Gemini API key; without it the app runs offline on fixtures |
| `MOCK_LLM` | `1` | `1` = fixtures instead of Gemini; set `0` for real calls |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model id |
| `GEMINI_THINKING_LEVEL` | `minimal` | `minimal` \| `low` \| `medium` \| `high` |
| `ANALYSIS_VERIFY` | `1` | Second pass that double-checks every detection |
| `ANALYSIS_TILING` / `ANALYSIS_TILE_MIN_SIDE` / `ANALYSIS_TILE_GRID` | `1` / `2000` / `4` | Tiled analysis for large images |
| `ANALYSIS_CACHE` | `1` | On-disk answer cache (`backend/app/analysis/.cache`) |
| `AI_ENABLED` | `1` | AI step on/off (also switchable at runtime) |
| `WATCH_ENABLED` / `WATCH_DIR` | `1` / `<repo>/input` | Watch-folder service |
| `FRAME_FPS` / `FRAME_MAX_SIDE` | `0.5` / `1920` | Video frame extraction |
| `MATCH_MAX_PAIRS` | `20` | Curated frame pairs per batch (caps Gemini calls at 2 per pair) |
| `BATCH_CRITERIA` | any physical change | What Gemini looks for in batch pairs |
| `FFMPEG_BIN` | PATH, else bundled | FFmpeg binary |

---

## Setup & run

**Prerequisites:** Python 3.9+, Node.js 18+, and optionally a Gemini API key.

**One command (Windows):**

```powershell
.\start.ps1          # creates backend\.venv, installs deps, starts backend :8000 and frontend :5173
.\start.ps1 mock     # same, forced offline (MOCK_LLM=1)
```

**Manual:**

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev          # http://localhost:5173, /api is proxied to :8000
```

Production frontend build: `cd frontend && npm run build` (output in `frontend/dist`).

To analyze one pair from the command line (from `backend/`):
`python -m app.analysis.cli a.jpg b.jpg "craters, new trenches" [--lang lt]`.

---

## Testing & evaluation

```bash
backend/.venv/Scripts/python -m pytest backend/tests -q   # 125 tests; MOCK_LLM=1 and WATCH_ENABLED=0 forced
cd frontend && npm run build                               # TypeScript check + production build
python eval/run.py [--configs mock,gemini] [--models a,b]  # precision / recall / IoU vs eval/labels
```

The tests cover alignment under rotation, mirroring, scale, crop and blur; heatmap golden outputs; prompt and preset
composition; mock filtering; tiling, cache and verification; API validation (presets, empty criteria, language, size);
and the batch pipeline with synthetic drone flights. Latest results are in [`eval/results.md`](eval/results.md); in
mock mode, precision and recall are both 1.00 with a mean IoU of 0.70 over 8 labelled changes.

---

## Project layout

```
backend/
  app/            FastAPI app, pipeline, alignment, diff, analysis, video, ingest, render, storage
  tests/          pytest suite
frontend/
  src/            App.tsx, components/, api.ts, types.ts, index.css
shared/
  sample_data/    demo pairs (pair01, pair02)
  fixtures/       offline analysis fixtures
eval/             labels, harness, results
docs/             architecture.md, api.md, review.md, team.md
tools/            make_oblique_pair.py (synthetic oblique test pairs)
UI.md             operator terminal design system
start.ps1         one-command launcher
```
