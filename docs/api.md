# HTTP API

## GET /api/health
`200 {"status":"ok"}`

## GET /api/samples
`200 [{"id": "pair01", "name": "...", "description": "...", "criteria": "...", "image_a_url": "...", "image_b_url": "..."}]`

## GET /api/samples/{pair_id}/{filename}
Streams demo sample image (e.g. `pair01/a.jpg`).

## POST /api/analyze
multipart/form-data: `image_a` (past), `image_b` (present), `criteria` (text), `lang` (optional, `en`|`lt`), `draw_grid` (optional, `true`|`false`).
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
Media dropped into the watch folder (`WATCH_DIR`) is paired by name and processed as a batch; see
[architecture.md](architecture.md#watch-folder-batch-pipeline-drone-video-and-image-pairs).

### GET /api/settings · PUT /api/settings
`200 {"ai_enabled": true, "ai_available": false, "watch_enabled": true, "watch_dir": "...", "frame_fps": 0.5, "max_pairs": 20}`
- `PUT` body `{"ai_enabled": false}` switches the AI step for batches queued from now on and for `/api/analyze`, until
  restart (`AI_ENABLED` is the default). `ai_available` is `false` when `MOCK_LLM=1` or no `GEMINI_API_KEY`: batches
  then fall back to CV results.

### GET /api/inbox
`200 {"watching": true, "folder": "...", "scheme": "<key>_<Before|After|DayN>, ...", "waiting": ["Lone_Day1.jpg"], "paired": [...], "rejected": [{"name": "clip.mp4", "reason": "name does not follow ..."}]}`

### GET /api/batches?limit=50
Most recent first: `[{"id", "site", "name_a", "name_b", "tag_a", "tag_b", "kind_a", "kind_b", "ai_enabled", "status", "stage", "progress", "frames_a", "frames_b", "matched_pairs", "pairs_count", "timings", "warnings", "error_message", "findings_count", "pending_count", "accepted_count", "rejected_count", ...}]`

Stages: `"queued"` ➔ `"extracting"` ➔ `"matching"` ➔ `"comparing"` (`progress` = `"3/12"`) ➔ `"done"` | `"error"`.
`kind_*` (`image` | `video`) comes from the file content, never the extension.

### GET /api/batches/{id}
The batch plus `pairs`: `[{"id", "idx", "frame_a", "frame_b", "time_a", "time_b", "inliers", "overlap", "ssim", "align_quality", "align_method", "change_ratio", "source": "ai"|"cv", "summary", "recommendation", "images": {"image_a_url", "aligned_b_url", "heatmap_url", "annotated_url"}, "findings": [...]}]`.
A finding: `{"id", "idx", "category", "type", "description", "location_text", "confidence", "box", "sector", "review_status": "pending"|"accepted"|"rejected", "reviewed_at"}`; `box` is in the A frame of its pair.

### POST /api/batches/{id}/rerun
Queues the same source files again with the current settings (e.g. AI switched on after a CV-only run) as a new
batch: `200 {"batch_id": "...", "status": "queued"}`. `404` unknown batch, `409` a source file is gone.

### POST /api/findings/{id}/review
Body `{"status": "accepted" | "rejected" | "pending"}` → the updated finding. `404` unknown finding, `422` other status.

### GET /api/batches/{id}/report?format=json|html
Download (`Content-Disposition: attachment`) of the verified change report: accepted findings only, with per-category
totals. `html` is one self-contained page (annotated frames and before/after crops embedded), printable to PDF.

## Conventions
- `box` = `[ymin, xmin, ymax, xmax]`, normalized 0–1000, origin top-left of image A frame (aligned B has A's size).
- Images are OpenCV BGR uint8 arrays inside Python, decoded from pixels only: EXIF orientation, file name, type and size never affect the comparison (the 25 MB limit is upload validation only).
- Sector = 4x4 grid, columns A–D, rows 1–4 (label = column letter + row number).
- Errors: `400` with descriptive error for undecodable images, empty criteria, or unsupported languages. `413` for images exceeding 25MB.
