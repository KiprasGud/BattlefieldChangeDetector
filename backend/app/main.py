"""PERSON 3: FastAPI app with non-blocking job model, history, and samples.
Also hosts the watch-folder batch pipeline (watcher + review API) for drone videos and image pairs."""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import batch, pipeline, settings  # noqa: E402
from .analysis import use_mock  # noqa: E402
from .analysis.presets import build_criteria, catalog, parse_ids  # noqa: E402
from .contracts import AnalyzeResponse  # noqa: E402
from .ingest import SCHEME, watcher  # noqa: E402
from .render import report  # noqa: E402
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
from .storage import batches as batch_store  # noqa: E402
from .video import frame_fps  # noqa: E402

pipeline.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_DATA_DIR = Path(__file__).resolve().parents[2] / "shared" / "sample_data"
init_db()
batch_store.init_batch_db()

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
executor = ThreadPoolExecutor(max_workers=4)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    batch.resume_interrupted()
    if watcher.watch_enabled():
        try:
            watcher.start_service()
        except RuntimeError as e:
            logging.getLogger(__name__).warning("Watch folder disabled: %s", e)
    yield
    watcher.stop_service()


app = FastAPI(title="Zvalgas AI - Battlefield Change Detector", lifespan=lifespan)

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


@app.get("/api/presets")
def list_presets():
    """Pre-made target classes for the criteria toggles; their instructions stay server-side."""
    return catalog()


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

    meta: dict[str, Any] = {}
    try:
        response = pipeline.run(
            bytes_a=bytes_a,
            bytes_b=bytes_b,
            criteria=criteria,
            lang=lang,
            draw_grid=draw_grid,
            job_id=job_id,
            stage_callback=on_stage,
            meta=meta,
        )
        complete_job(
            job_id=job_id,
            result=response.result.model_dump(),
            align_quality=response.align_quality,
            align_ok=response.align_ok,
            align_method=meta.get("align_method", "none"),
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
    criteria: str = Form(""),
    presets: str = Form(""),
    lang: str = Form("en"),
    draw_grid: bool = Form(False),
    sync: bool = Query(False),
):
    """criteria: the operator's free-text query; presets: comma-separated target class ids (GET /api/presets).
    Both become one written instruction for the AI model."""
    try:
        cleaned_criteria = build_criteria(parse_ids(presets), criteria)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not cleaned_criteria:
        raise HTTPException(status_code=400, detail="Search criteria cannot be empty: select a target class or enter a query.")

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


# --- watch-folder batches and review ---------------------------------------------------------------

class SettingsUpdate(BaseModel):
    ai_enabled: bool


class ReviewUpdate(BaseModel):
    status: Literal["pending", "accepted", "rejected"]


def _settings() -> dict[str, Any]:
    svc = watcher.service()
    return {
        "ai_enabled": settings.ai_enabled(),
        "ai_available": not use_mock(),
        "watch_enabled": svc is not None,
        "watch_dir": str(svc.folder if svc else watcher.watch_dir()),
        "frame_fps": frame_fps(),
        "max_pairs": batch.max_pairs(),
    }


@app.get("/api/settings")
def get_settings():
    return _settings()


@app.put("/api/settings")
def put_settings(update: SettingsUpdate):
    """Switch the AI step for batches queued from now on (and for /api/analyze) until restart."""
    settings.set_ai_enabled(update.ai_enabled)
    return _settings()


@app.get("/api/inbox")
def get_inbox():
    """Files in the watch folder waiting for a partner, and names that do not follow the scheme."""
    svc = watcher.service()
    snapshot = svc.inbox.snapshot() if svc else {"waiting": [], "paired": [], "rejected": []}
    return {"watching": svc is not None, "folder": _settings()["watch_dir"], "scheme": SCHEME, **snapshot}


@app.get("/api/batches")
def get_batches(limit: int = Query(50, ge=1, le=200)):
    return batch_store.list_batches(limit)


@app.get("/api/batches/{batch_id}")
def get_batch_detail(batch_id: str):
    detail = batch_store.batch_detail(batch_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return detail


@app.post("/api/batches/{batch_id}/rerun")
def rerun_batch(batch_id: str):
    """Process the same sources again with the current settings, as a new batch."""
    try:
        new_id = batch.rerun_batch(batch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Batch not found")
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))
    batch.worker.submit(new_id)
    return {"batch_id": new_id, "status": "queued"}


@app.post("/api/findings/{finding_id}/review")
def review_finding(finding_id: str, update: ReviewUpdate):
    finding = batch_store.set_review(finding_id, update.status)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@app.get("/api/batches/{batch_id}/report")
def batch_report(batch_id: str, fmt: Literal["json", "html"] = Query("json", alias="format")):
    """Final report of the verified (accepted) findings, as a download."""
    detail = batch_store.batch_detail(batch_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    headers = {"Content-Disposition": f'attachment; filename="zvalgas_report_{batch_id}.{fmt}"'}
    if fmt == "html":
        return HTMLResponse(report.build_html(detail, batch.BATCH_DIR / batch_id), headers=headers)
    return JSONResponse(report.build_json(detail), headers=headers)
