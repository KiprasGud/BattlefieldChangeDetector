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

## GET /api/jobs
Returns list of recent missions:
`200 [{"job_id": "...", "created_at": "...", "status": "done", "criteria": "...", "summary": "...", "changes_count": 2, ...}]`

## Conventions
- `box` = `[ymin, xmin, ymax, xmax]`, normalized 0–1000, origin top-left of image A frame (aligned B has A's size).
- Images are OpenCV BGR uint8 arrays inside Python.
- Sector = 4x4 grid, columns A–D, rows 1–4 (label = column letter + row number).
- Errors: `400` with descriptive error for undecodable images, empty criteria, or unsupported languages. `413` for images exceeding 25MB.
