# HTTP API (frozen)

## GET /api/health
`200 {"status":"ok"}`

## GET /api/samples
`200 [{"id": "pair01", "name": "...", "description": "...", "criteria": "...", "image_a_url": "...", "image_b_url": "..."}]`

## GET /api/samples/{pair_id}/{filename}
Streams demo sample image (e.g. `pair01/a.jpg`).

## POST /api/analyze
multipart/form-data: `image_a` (past), `image_b` (present), `criteria` (text), `lang` (optional, `en`|`lt`), `draw_grid` (optional, `true`|`false`).

Response (`AnalyzeResponse`, see `backend/app/contracts.py` / `frontend/src/types.ts`):
```json
{
  "job_id": "ab12cd34ef56",
  "result": { "report_date": "...", "summary": "...", "changes": [ { "type": "...", "description": "...", "location_text": "...", "confidence": "high", "box": [ymin, xmin, ymax, xmax], "sector": "B4" } ], "recommendation": "..." },
  "align_quality": 0.0,
  "align_ok": true,
  "images": { "aligned_b_url": "/api/files/<job>/aligned_b.jpg", "annotated_url": "/api/files/<job>/annotated.jpg", "image_a_url": "/api/files/<job>/image_a.jpg" }
}
```

## Conventions
- `box` = `[ymin, xmin, ymax, xmax]`, normalized 0–1000, origin top-left of image A frame (aligned B has A's size).
- Images are OpenCV BGR uint8 arrays inside Python.
- Sector = 4x4 grid, columns A–D, rows 1–4 (label = column letter + row number).
- Errors: `400` with descriptive error for undecodable images, empty criteria, or unsupported languages. `413` for images exceeding 25MB.
