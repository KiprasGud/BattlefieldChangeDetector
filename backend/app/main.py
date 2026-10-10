"""PERSON 3: FastAPI app. Run: uvicorn app.main:app --reload (from backend/)."""
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import pipeline  # noqa: E402
from .contracts import AnalyzeResponse  # noqa: E402

pipeline.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_DATA_DIR = Path(__file__).resolve().parents[2] / "shared" / "sample_data"

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

app = FastAPI(title="Zvalgas AI - Battlefield Change Detector")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/api/files", StaticFiles(directory=pipeline.OUTPUT_DIR), name="files")


@app.get("/api/health")
def health():
    return {"status": "ok"}


SAMPLE_METADATA = {
    "pair01": {
        "name": "Sample 01 - Treeline & Roadway",
        "description": "Forward treeline activity: vehicle tracks and fresh impact craters.",
        "criteria": "New vehicle tracks, craters / digging",
    },
    "pair02": {
        "name": "Sample 02 - Fortified Post & Junction",
        "description": "Logistical checkpoint: perimeter modifications and vehicle movement.",
        "criteria": "Vehicle activity, barrier breaches, felled trees",
    },
}


@app.get("/api/samples")
def list_samples():
    """Returns available sample pairs for demo/testing."""
    samples = []
    if SAMPLE_DATA_DIR.exists():
        for pair_dir in sorted(SAMPLE_DATA_DIR.iterdir()):
            if pair_dir.is_dir():
                pair_id = pair_dir.name
                meta = SAMPLE_METADATA.get(
                    pair_id,
                    {
                        "name": f"Demo Pair {pair_id}",
                        "description": "Demonstration reconnaissance pair",
                        "criteria": "New vehicle tracks, craters / digging",
                    },
                )
                file_a = pair_dir / "a.jpg"
                file_b = pair_dir / "b.jpg"
                if file_a.exists() and file_b.exists():
                    samples.append(
                        {
                            "id": pair_id,
                            "name": meta["name"],
                            "description": meta["description"],
                            "criteria": meta["criteria"],
                            "image_a_url": f"/api/samples/{pair_id}/a.jpg",
                            "image_b_url": f"/api/samples/{pair_id}/b.jpg",
                        }
                    )
    return samples


@app.get("/api/samples/{pair_id}/{filename}")
def get_sample_file(pair_id: str, filename: str):
    """Serves sample image files safely."""
    # Sanitize pair_id and filename to prevent path traversal
    safe_pair_id = Path(pair_id).name
    safe_filename = Path(filename).name
    file_path = SAMPLE_DATA_DIR / safe_pair_id / safe_filename
    if not file_path.resolve().is_file() or not str(file_path.resolve()).startswith(str(SAMPLE_DATA_DIR.resolve())):
        raise HTTPException(status_code=404, detail="Sample file not found")
    return FileResponse(path=file_path, media_type="image/jpeg")


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_endpoint(
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    criteria: str = Form(...),
    lang: str = Form("en"),
    draw_grid: bool = Form(False),
):
    # Validation: criteria
    cleaned_criteria = criteria.strip()
    if not cleaned_criteria:
        raise HTTPException(status_code=400, detail="Search criteria cannot be empty.")

    # Validation: lang
    if lang not in ("en", "lt"):
        raise HTTPException(status_code=400, detail="Invalid language: must be 'en' or 'lt'.")

    # Read bytes and validate file sizes
    bytes_a = await image_a.read()
    bytes_b = await image_b.read()

    if len(bytes_a) > MAX_FILE_SIZE_BYTES or len(bytes_b) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image upload size exceeds the maximum limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
        )

    try:
        return pipeline.run(bytes_a, bytes_b, cleaned_criteria, lang, draw_grid=draw_grid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")
