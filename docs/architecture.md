# Architecture

```
 Operator (React UI)
   │  image A (past), image B (present), criteria
   ▼
 FastAPI  POST /api/analyze            (main.py, pipeline.py)   [P3]
   │
   ├─1─ align(A, B)  → B warped into A's frame + quality       (alignment/)  [P1]
   │      OpenCV: SIFT/ORB → ratio test → RANSAC homography (ECC fallback)
   │
   ├─2─ analyze(A, B', criteria) → AnalysisResult               (analysis/)   [P2]
   │      Gemini vision, IMINT prompt + few-shot, JSON-schema output, boxes 0-1000
   │
   └─3─ annotate(B', result) → red boxes                        (render/)     [P3]
   ▼
 UI: annotated image + change list + report + recommendation
```
Interfaces between stages are in `backend/app/contracts.py`. Each stage ships a stub so the full flow works from hour 0.
