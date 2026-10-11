"""/api/demo: the demo cache endpoints prep mode uses. Served only by the demo prep server (app.demo_app); the
production app (app.main) never includes this router."""
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import settings
from ..analysis import cache as answer_cache
from ..analysis import use_mock
from ..analysis.gemini_client import model_name
from ..storage import get_job
from . import store

MAX_SOURCE_BYTES = 25 * 1024 * 1024  # the /api/analyze upload limit, which the originals already passed

router = APIRouter(prefix="/api/demo", tags=["demo"])


class SceneMeta(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None


class SceneOrder(BaseModel):
    ids: list[str]


@router.get("/status")
def demo_status():
    """What a prep run uses: the model, live Gemini or offline fixtures, the AI switch, the answer cache."""
    return {
        "model": model_name(),
        "live": not use_mock(),
        "ai_enabled": settings.ai_enabled(),
        "answer_cache": answer_cache.enabled(),
        "cache_dir": str(store.cache_dir()),
    }


@router.get("/scenes")
def list_scenes():
    """Cached scenes in presentation order."""
    return {"scenes": store.list_scenes()}


@router.post("/scenes")
def cache_scene(
    job_id: str = Form(""),
    title: str = Form(""),
    subtitle: str = Form(""),
    scene_id: str = Form(""),
    source_a: Optional[UploadFile] = File(None),
    source_b: Optional[UploadFile] = File(None),
):
    """Cache State: freeze a finished job (its images and AI output) as a scene. scene_id replaces that scene in
    place; empty appends a new one. source_a / source_b: the original uploads, kept byte for byte."""
    job = get_job(job_id) if job_id else None
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found (jobs are pruned after 24 h).")
    sources = {}
    for key, upload in (("source_a", source_a), ("source_b", source_b)):
        if upload is None:
            continue
        data = upload.file.read()
        if len(data) > MAX_SOURCE_BYTES:
            raise HTTPException(status_code=413, detail=f"{key} exceeds {MAX_SOURCE_BYTES // (1024 * 1024)} MB.")
        sources[key] = (upload.filename or key, data)
    try:
        return store.save_scene(job, title, subtitle, sources, scene_id or None)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id!r} not found.")
    except store.JobNotReady as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:  # e.g. a scene file still open while it is replaced (Windows)
        raise HTTPException(status_code=409, detail=f"Cannot write the scene files, try again: {e}")


@router.patch("/scenes/{scene_id}")
def rename_scene(scene_id: str, meta: SceneMeta):
    try:
        return store.rename_scene(scene_id, meta.title, meta.subtitle)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id!r} not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/order")
def reorder_scenes(order: SceneOrder):
    try:
        return {"scenes": store.set_order(order.ids)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str):
    try:
        store.delete_scene(scene_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id!r} not found.")
    return {"deleted": scene_id}
