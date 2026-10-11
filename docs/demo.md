# Demo presentation mode

A failure-proof live demo: results are prepared and checked ahead of time, then shown from disk. The presentation
makes no API or AI calls, so there is nothing to wait for and nothing that can fail in front of the audience.

The demo is a separate layer. It does not change the operator terminal (`start.ps1`, `index.html`, `App.tsx`, `app.main`):

| | Operator terminal | Demo prep (admin) | Presentation (audience) |
|---|---|---|---|
| Start | `.\start.ps1` | `.\demo.ps1 prep` | double-click `present.cmd` (or `.\demo.ps1`) |
| Page | http://localhost:5173 | http://localhost:5174/prep.html | http://localhost:5175/demo.html |
| Backend | `app.main:app` :8000 | `app.demo_app:app` :8010 | none |
| AI calls | yes | yes (live, fresh on every run) | **never** |

All three can run at the same time.

## 1. Prep: run, review, re-prompt, cache

```powershell
.\demo.ps1 prep
```

This starts the demo prep server on :8010 and opens the prep page. The server runs with these settings, for its own
process only:

| Setting | Value | Why |
|---|---|---|
| `MOCK_LLM` | `0` | Live Gemini (`GEMINI_API_KEY` from `.env`) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | The demo model |
| `AI_ENABLED` | `1` | The AI step is on |
| `ANALYSIS_CACHE` | `0` | Every RUN calls the model again, so re-running gives a new answer |
| `WATCH_ENABLED`, `AUTO_BATCH` | `0` | The operator terminal keeps sole charge of the watch folder and batches |

The prep page header shows `AI: LIVE GEMINI-3.5-FLASH-LITE` in green. A red `AI: OFFLINE FIXTURES` means
there is no API key: the runs then come from offline fixtures, not from the model.

Workflow:
1. **Pick a pair.** Use the baseline/recon dropzones (`Alt+B` / `Alt+C`) or a sample pair.
2. **Set the prompt.** Pick target classes (`Alt+1`…`Alt+8`) and/or type a custom query (`/`). Choose the report
   language (EN/LT).
3. **`F5` RUN AI.** Review the boxes and labels in the viewer (slider / HUD / split / heatmap) and in the
   detection list (`↑`/`↓`). Read the summary, the recommendation and the warnings.
4. **Wrong detection?** Change the prompt or swap an image, then press `F5` again. A red banner warns when a run
   fell back to offline fixtures, for example because of an API error or quota.
5. **Perfect?** Type the title the audience will see, plus an optional subtitle, and press **`Ctrl+S` CACHE STATE**.
   It always stores the last run: the exact images it ran on and the AI's JSON output, exactly as returned.
6. **Manage scenes.** Use the cached-scene list:
   - `▲`/`▼`: presentation order;
   - `REN`: rename;
   - `DEL`: delete;
   - `LOAD`: put a scene back into the editor (images, prompt, title). Press `F5` to re-run, then **UPDATE SCENE**
     replaces it in place.
   - `Alt+N`: start a new scene.
7. **`Alt+P` LAUNCH PRESENTATION** opens the presentation in a new window as a rehearsal.

Detections are never edited by hand. To fix one, re-prompt and run again.

## 2. Present

Double-click **`present.cmd`**, or run `.\demo.ps1`. It:
1. checks that every cached scene is complete. Otherwise it stops with a message before anything is shown;
2. builds the presentation bundle (`frontend/dist-demo/`), only when the code changed since the last build;
3. starts a static server on :5175, hidden;
4. opens Chrome or Edge as a full-screen app window, falling back to the default browser.

Closing the window stops the server.

| Key | Action |
|---|---|
| `Enter` | Start, from the title card |
| `→` `PageDown` `Space` / `←` `PageUp` | Next / previous scene (presenter remotes send PageUp/PageDown) |
| `Home` / `End` | Title card / last scene |
| `↑` / `↓`, click a box | Highlight a target on both images, with its details |
| `Esc` | Clear the highlight |
| `F` | Toggle fullscreen |
| `Alt+S` | Light theme, for washed-out projectors |

The view shows only the scene title, baseline and aligned recon side by side with the AI boxes, the target list,
the tasking, the assessment and the recommendation. It never shows the system log, warnings, timings, alignment
stats, settings or the heatmap. It makes no API requests and writes nothing to the console. The audience server
does not serve the prep page and has no `/api` proxy.

Run the presentation once before the audience arrives: the first launch after a code change builds the bundle,
which takes a few seconds. Fonts come from Google Fonts like the operator terminal. Offline, the system fonts are
used instead and nothing breaks.

## Cache layout

`demo_cache/` in the repository root (override with the absolute path `DEMO_CACHE_DIR`, read by both the prep
server and `vite.demo.config.ts`):

```
demo_cache/manifest.json            {"version": 1, "updated_at": "...", "scenes": ["treeline-roadway-3f9a1c", ...]}
demo_cache/<scene id>/scene.json    title, subtitle, criteria, presets, query, lang, source, model, size, align,
                                    warnings, timings, result (the AI output verbatim), files
demo_cache/<scene id>/image_a.jpg   image A as analyzed
demo_cache/<scene id>/aligned_b.jpg image B registered into A's frame (the boxes are in this frame)
demo_cache/<scene id>/annotated.jpg boxes burned in
demo_cache/<scene id>/source_a.*    the exact original uploads, byte for byte
demo_cache/<scene id>/source_b.*
```

`source` is `gemini`, `fixtures` (offline mock) or `ai_off`. The presentation shows the model name only for
`gemini` scenes. The folder is not gitignored: commit it to present from another machine.

## Prep API (demo prep server only)

| Method & path | Purpose |
|---|---|
| `GET /api/demo/status` | `{model, live, ai_enabled, answer_cache, cache_dir}` |
| `GET /api/demo/scenes` | Cached scenes in presentation order |
| `POST /api/demo/scenes` | multipart: `job_id`, `title`, `subtitle?`, `scene_id?` (replace in place), `source_a?`, `source_b?`. `404` unknown job/scene, `409` job unfinished or its output pruned (jobs live 24 h), `400` empty title, `413` > 25 MB |
| `PATCH /api/demo/scenes/{id}` | `{title?, subtitle?}` |
| `PUT /api/demo/order` | `{ids}`: every cached scene exactly once, else `400` |
| `DELETE /api/demo/scenes/{id}` | Remove the scene and its files |

Everything else on :8010 (`/api/analyze`, `/api/jobs`, `/api/files`, ...) is the unchanged production app, mounted.
A mounted app gets no lifespan: the prep server never starts the watch folder or the batch worker, and never
re-queues batches. `backend/tests/test_demo.py` pins this.

## Files

| Path | Role |
|---|---|
| `backend/app/demo_app.py` | Demo prep server: `/api/demo` + the production app mounted |
| `backend/app/demo/store.py`, `routes.py` | Cache writes (atomic, retried while Windows reports a file busy) and endpoints |
| `frontend/demo.html`, `src/demo/present.tsx`, `Presentation.tsx`, `SceneFrames.tsx` | Presentation view |
| `frontend/prep.html`, `src/demo/prep.tsx`, `PrepMode.tsx`, `prepApi.ts` | Prep mode; reuses `api.ts` `analyze`/`fetchPresets` and `ResultViewer` |
| `frontend/src/demo/scene.ts`, `demo.css` | Static cache reader, styles on top of `index.css` |
| `frontend/vite.demo.config.ts` | Ports, `/demo_cache` file serving, presentation-only build |
| `demo.ps1`, `present.cmd` | Launchers |
