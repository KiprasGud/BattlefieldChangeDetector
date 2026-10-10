# HTTP API

## GET /api/health
`200 {"status":"ok"}`

## GET /api/samples
`200 [{"id": "pair01", "name": "...", "description": "...", "criteria": "...", "image_a_url": "...", "image_b_url": "..."}]`

## GET /api/samples/{pair_id}/{filename}
Streams demo sample image (e.g. `pair01/a.jpg`).

## GET /api/presets
Pre-made target classes for the criteria toggles.
`200 [{"id": "craters", "label": "Craters / Artillery Impacts", "shortcut": "Alt+2"}, ...]`
Ids: `wires`, `craters`, `trenches`, `tracks`, `camouflage`, `damage`, `vehicles`, `felled_trees`.

## POST /api/analyze
multipart/form-data: `image_a` (past), `image_b` (present), `criteria` (optional free-text query), `presets` (optional,
comma-separated ids from `/api/presets`), `lang` (optional, `en`|`lt`), `draw_grid` (optional, `true`|`false`).
At least one of `criteria` / `presets` is required. Each preset is expanded server-side into a written visual
instruction and bundled with the free-text query into one criteria block for the AI model (the stored job `criteria`
is that block). OpenCV only aligns the images: it never detects. With the AI step off, no detections are returned.
Query parameter: `sync` (optional boolean, default `false`).

- **Asynchronous (default)**: Returns `200` with:
```json
{
  "job_id": "ab12cd34ef56",
  "status": "queued",
  "stage": "queued"
}
```
Client then polls `GET /api/jobs/{job_id}`.

- **Synchronous (`?sync=true`)**: Returns full `AnalyzeResponse`.

## GET /api/jobs/{job_id}
Returns job execution state, live stage progression, timings, warnings, and result:
```json
{
  "job_id": "ab12cd34ef56",
  "status": "done",
  "stage": "done",
  "timings": { "align": 0.12, "heatmap": 0.05, "ai": 0.85, "render": 0.04, "total": 1.06 },
  "warnings": [],
  "result": { "report_date": "...", "summary": "...", "changes": [...], "recommendation": "..." },
  "align_quality": 0.98,
  "align_ok": true,
  "align_method": "sift",
  "images": {
    "image_a_url": "/api/files/<job>/image_a.jpg",
    "aligned_b_url": "/api/files/<job>/aligned_b.jpg",
    "annotated_url": "/api/files/<job>/annotated.jpg",
    "heatmap_url": "/api/files/<job>/heatmap.jpg"
  }
}
```

Stages: `"queued"` ➔ `"aligning"` ➔ `"heatmap"` ➔ `"ai"` ➔ `"render"` ➔ `"done"` | `"error"`.

- `align_ok`: `true` when B was visually matched to A (same scene). `false` means no reliable match: B is shown only resized to A's frame.
- `align_quality`: 0–1 visual agreement of A and aligned B over their overlap (normalized cross-correlation).
- `align_method`: `"sift"` (feature match), `"ecc"` (fallback for feature-poor, nearly aligned pairs) or `"none"`.
- `warnings` may contain: `"Images could not be matched visually …"` (`align_ok=false`), `"Image B is mirrored relative to Image A; corrected during alignment."`, `"Fallback ECC alignment applied …"`, `"OFFLINE MODE: …"` (fixture data instead of Gemini, with the reason), and `"AI step disabled: …"` (AI switched off: the changes are the heatmap's candidate regions, category `unknown_anomaly`, confidence `low`).
- Every change has a `category`: `missing_object`, `new_structure`, `terrain_change` or `unknown_anomaly`.

## GET /api/jobs
Returns list of recent missions:
`200 [{"job_id": "...", "created_at": "...", "status": "done", "criteria": "...", "summary": "...", "changes_count": 2, ...}]`

## Watch-folder batches and review
Media dropped into the watch folder (`WATCH_DIR`) is grouped by name: every epoch of one project (naming key) is one
batch, with one *leg* per consecutive epoch step (`Day1→Day2`, `Day2→Day5`); see
[architecture.md](architecture.md#watch-folder-batch-pipeline-drone-video-and-image-pairs).

### GET /api/settings · PUT /api/settings
`200 {"ai_enabled": true, "ai_available": false, "auto_batch": true, "queued_count": 0, "watch_enabled": true, "watch_dir": "...", "frame_fps": 0.5, "max_pairs": 20}`
- `PUT` body `{"ai_enabled": false}` switches the AI step for batches queued from now on and for `/api/analyze`, until
  restart (`AI_ENABLED` is the default). `ai_available` is `false` when `MOCK_LLM=1` or no `GEMINI_API_KEY`: batches
  then fall back to CV results.
- `PUT` body `{"auto_batch": false}` stops automatic batching until restart (`AUTO_BATCH` is the default): settled
  files stay in the inbox unbatched and the worker pauses after the batch it is running. `{"auto_batch": true}`
  batches every project waiting in the inbox and resumes the worker. Both fields are optional.

### POST /api/queue/clear
Only while automatic batching is stopped (`409` otherwise). Flushes every `queued` batch; the running one is left
alone. A batch with no finished leg is deleted; a batch re-opened by a new epoch loses only its unfinished legs and
goes back to `done`, so finished reviews survive. Its files show up in the inbox as unbatched again.
`200 {"deleted": ["<batch id>", ...], "files": ["ProjectX_Day5.jpg", ...]}`

### GET /api/inbox
`200 {"watching": true, "folder": "...", "scheme": "<key>_<Before|After|DayN>, ...", "waiting": ["Lone_Day1.jpg"], "paired": [...], "rejected": [{"name": "clip.mp4", "reason": "name does not follow ..."}], "groups": [{"project": "projectx", "site": "ProjectX", "files": [...], "epochs": ["Day1", "Day2", "Day5"], "batched": false}]}`

`batched` is `true` when every consecutive file pair of the project is a leg (not failed) of a batch.
`pairs` lists every consecutive file pair of those projects, batched or not (the dashboard's pairs view keeps them all):
`[{"project", "site", "name_a", "name_b", "tag_a", "tag_b", "batched"}]`, `batched` by the same rule, per pair.

### POST /api/inbox/batch
Body `{"name_a": "ProjectX_Day1.jpg", "name_b": "ProjectX_Day2.jpg"}`: batch that one inbox pair by hand and run it now,
also while automatic batching is stopped (it skips the paused worker; queued automatic batches still wait). The pair
becomes a leg of the project's batch, as automatic batching would add it.
`200 {"batch_id": "...", "started": true}`; `started` is `false` (`batch_id` `null`) when the project's batch is already
running (it picks the leg up) or the pair was batched before. `404` watcher off or not a consecutive inbox pair.

### GET /api/batches?limit=50
Most recent first, one row per project batch: `[{"id", "site", "project", "legs_count", "name_a", "name_b", "tag_a", "tag_b", "kind_a", "kind_b", "ai_enabled", "status", "stage", "progress", "frames_a", "frames_b", "matched_pairs", "pairs_count", "timings", "warnings", "error_message", "findings_count", "pending_count", "accepted_count", "rejected_count", ...}]`

`*_a` is the project's first epoch, `*_b` its latest. Stages: `"queued"` ➔ `"extracting"` ➔ `"matching"` ➔
`"comparing"` (`progress` = `"Day1→Day2 3/12"`) ➔ `"done"` | `"error"`, repeated per leg. The batch is `error` only
when every leg failed; leg warnings and errors are listed in `warnings`, prefixed by the leg.
`kind_*` (`image` | `video`) comes from the file content, never the extension.

### GET /api/batches/{id}
The batch plus `legs`: `[{"id", "idx", "tag_a", "tag_b", "name_a", "name_b", "kind_a", "kind_b", "status": "pending"|"running"|"done"|"error", "frames_a", "frames_b", "matched_pairs", "timings", "warnings", "error_message"}]`
and `pairs` (numbered across the whole batch): `[{"id", "leg_idx", "tag_a", "tag_b", "kind_a", "kind_b", "idx", "frame_a", "frame_b", "time_a", "time_b", "inliers", "overlap", "ssim", "align_quality", "align_method", "change_ratio", "source": "ai"|"cv", "summary", "recommendation", "images": {"image_a_url", "aligned_b_url", "heatmap_url", "annotated_url"}, "findings": [...]}]`.
A finding: `{"id", "idx", "category", "type", "description", "location_text", "confidence", "box", "sector", "review_status": "pending"|"accepted"|"rejected", "reviewed_at"}`; `box` is in the A frame of its pair.

### POST /api/batches/{id}/rerun
Queues the same source files (every leg) again with the current settings (e.g. AI switched on after a CV-only run)
as a new batch: `200 {"batch_id": "...", "status": "queued"}`. `404` unknown batch, `409` a source file is gone.

### POST /api/findings/{id}/review
Body `{"status": "accepted" | "rejected" | "pending"}` → the updated finding. `404` unknown finding, `422` other status.

### GET /api/batches/{id}/report?format=json|html|pdf
Download (`Content-Disposition: attachment`) of the verified change report: accepted findings only, with per-category
totals. `html` is one self-contained page (annotated frames and before/after crops embedded), printable to PDF.
`pdf` (A4, fpdf2) shows each pair's A and aligned B side by side with the boxes drawn on both, then its findings grouped
by category with before/after crops.
The JSON lists the `legs`; each verified change carries its `leg` and `leg_label`. The review dashboard also shows
this report in place (`[V]`), from the batch detail, without a download.

## Conventions
- `box` = `[ymin, xmin, ymax, xmax]`, normalized 0–1000, origin top-left of image A frame (aligned B has A's size).
- Images are OpenCV BGR uint8 arrays inside Python, decoded from pixels only: EXIF orientation, file name, type and size never affect the comparison (the 25 MB limit is upload validation only).
- Sector = 4x4 grid, columns A–D, rows 1–4 (label = column letter + row number).
- Errors: `400` with descriptive error for undecodable images, empty criteria, or unsupported languages. `413` for images exceeding 25MB.
