"""PERSON 3: FastAPI app with non-blocking job model, history, and samples."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import pipeline  # noqa: E402
from .contracts import AnalyzeResponse  # noqa: E402
from .storage import (  # noqa: E402
    complete_job,
    create_job,
    fail_job,
    get_job,
    init_db,
    list_jobs,
    prune_old_jobs,
    update_job_stage,
)

pipeline.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_DATA_DIR = Path(__file__).resolve().parents[2] / "shared" / "sample_data"
init_db()

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
executor = ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="Zvalgas AI - Battlefield Change Detector")

# Fix CORS (#10): allow_credentials=False with wildcard origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
    safe_pair_id = Path(pair_id).name
    safe_filename = Path(filename).name
    file_path = SAMPLE_DATA_DIR / safe_pair_id / safe_filename
    if not file_path.resolve().is_file() or not str(file_path.resolve()).startswith(str(SAMPLE_DATA_DIR.resolve())):
        raise HTTPException(status_code=404, detail="Sample file not found")
    return FileResponse(path=file_path, media_type="image/jpeg")


def _run_job_worker(
    job_id: str,
    bytes_a: bytes,
    bytes_b: bytes,
    criteria: str,
    lang: str,
    draw_grid: bool,
) -> None:
    def on_stage(stage: str, timings: Optional[dict[str, float]] = None):
        update_job_stage(job_id, stage, timings)

    try:
        response = pipeline.run(
            bytes_a=bytes_a,
            bytes_b=bytes_b,
            criteria=criteria,
            lang=lang,
            draw_grid=draw_grid,
            job_id=job_id,
            stage_callback=on_stage,
        )
        complete_job(
            job_id=job_id,
            result=response.result.model_dump(),
            align_quality=response.align_quality,
            align_ok=response.align_ok,
            align_method="sift" if response.align_ok else "none",
            images=response.images,
            timings=response.timings,
            warnings=response.warnings,
        )
    except Exception as e:
        fail_job(job_id, str(e))
    finally:
        prune_old_jobs(max_count=50, max_age_hours=24)


@app.post("/api/analyze")
async def analyze_endpoint(
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    criteria: str = Form(...),
    lang: str = Form("en"),
    draw_grid: bool = Form(False),
    sync: bool = Query(False),
):
    cleaned_criteria = criteria.strip()
    if not cleaned_criteria:
        raise HTTPException(status_code=400, detail="Search criteria cannot be empty.")

    if lang not in ("en", "lt"):
        raise HTTPException(status_code=400, detail="Invalid language: must be 'en' or 'lt'.")

    bytes_a = await image_a.read()
    bytes_b = await image_b.read()

    if len(bytes_a) > MAX_FILE_SIZE_BYTES or len(bytes_b) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image upload size exceeds the maximum limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
        )

    job_id = uuid.uuid4().hex[:12]
    create_job(job_id=job_id, criteria=cleaned_criteria, lang=lang)

    if sync:
        try:
            _run_job_worker(job_id, bytes_a, bytes_b, cleaned_criteria, lang, draw_grid)
            job_data = get_job(job_id)
            if not job_data or job_data.get("status") == "error":
                raise ValueError(job_data.get("error_message", "Unknown error") if job_data else "Failed")
            return AnalyzeResponse(
                job_id=job_id,
                result=job_data["result"],
                align_quality=job_data["align_quality"],
                align_ok=job_data["align_ok"],
                images=job_data["images"],
                timings=job_data["timings"],
                warnings=job_data["warnings"],
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")

    # Non-blocking async job execution
    executor.submit(
        _run_job_worker,
        job_id,
        bytes_a,
        bytes_b,
        cleaned_criteria,
        lang,
        draw_grid,
    )
    return {"job_id": job_id, "status": "queued", "stage": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    """Returns current status, stage, timings, warnings, and result for a job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs")
def get_jobs_history(limit: int = Query(50, ge=1, le=100)):
    """Returns list of recent analysis missions."""
    return list_jobs(limit=limit)
