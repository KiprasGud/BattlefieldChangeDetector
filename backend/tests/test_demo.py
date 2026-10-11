"""Demo layer (app/demo, app.demo_app): prep mode caches finished jobs as presentation scenes."""
import json
import uuid
from pathlib import Path

import cv2
import pytest
from fastapi.testclient import TestClient

from app import batch, demo_app, main, pipeline
from app.demo import store
from app.storage import complete_job, create_job

PAIR = Path(__file__).resolve().parents[2] / "shared" / "sample_data" / "pair01"
SOURCE_A, SOURCE_B = (PAIR / "a.jpg").read_bytes(), (PAIR / "b.jpg").read_bytes()


@pytest.fixture(scope="module")
def client():
    return TestClient(demo_app.app)


@pytest.fixture(scope="module")
def job(client):
    """One finished analysis (offline fixtures), run through the production endpoint the demo app mounts."""
    r = client.post(
        "/api/analyze?sync=true",
        files={"image_a": ("a.jpg", SOURCE_A, "image/jpeg"), "image_b": ("b.jpg", SOURCE_B, "image/jpeg")},
        data={"presets": "craters", "criteria": "fresh digging"},
    )
    assert r.status_code == 200, r.text
    return client.get(f"/api/jobs/{r.json()['job_id']}").json()


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_CACHE_DIR", str(tmp_path / "demo_cache"))
    return tmp_path / "demo_cache"


def _cache(client, job_id, title="Treeline", **form):
    files = {"source_a": ("Baseline.JPG", SOURCE_A, "image/jpeg"), "source_b": ("recon.jpg", SOURCE_B, "image/jpeg")}
    return client.post("/api/demo/scenes", data={"job_id": job_id, "title": title, **form}, files=files)


def _ids(client):
    return [s["id"] for s in client.get("/api/demo/scenes").json()["scenes"]]


def test_production_app_has_no_demo_routes():
    assert TestClient(main.app).get("/api/demo/scenes").status_code == 404


def test_demo_app_skips_the_production_lifespan(monkeypatch):
    calls = []
    monkeypatch.setattr(batch, "sync_worker", lambda: calls.append("sync"))
    monkeypatch.setattr(batch, "resume_interrupted", lambda: calls.append("resume") or [])
    with TestClient(demo_app.app) as c:  # runs the demo app's own (empty) lifespan
        assert c.get("/api/health").json() == {"status": "ok"}  # production routes through the mount
    assert calls == []
    with TestClient(main.app):  # control: served alone, the production app does run its lifespan
        pass
    assert calls == ["sync", "resume"]


def test_status_reports_offline_fixtures(client, cache):
    status = client.get("/api/demo/status").json()
    assert status["live"] is False  # MOCK_LLM=1 in tests
    assert status["model"] and status["cache_dir"] == str(cache)


def test_cache_state_freezes_images_and_ai_output(client, job, cache):
    r = _cache(client, job["job_id"], subtitle="  Fresh craters ")
    assert r.status_code == 200, r.text
    scene = r.json()
    folder = cache / scene["id"]
    assert scene["id"].startswith("treeline-")
    assert (folder / "source_a.jpg").read_bytes() == SOURCE_A  # the exact original, suffix lowercased
    assert (folder / "source_b.jpg").read_bytes() == SOURCE_B
    for name in ("image_a.jpg", "aligned_b.jpg", "annotated.jpg"):
        assert (folder / name).read_bytes() == (pipeline.OUTPUT_DIR / job["job_id"] / name).read_bytes()
    assert not (folder / "heatmap.jpg").exists()

    stored = json.loads((folder / "scene.json").read_text(encoding="utf-8"))
    assert stored == scene
    assert stored["result"] == job["result"] and stored["result"]["changes"]  # the AI output, verbatim
    assert stored["subtitle"] == "Fresh craters"
    assert (stored["presets"], stored["query"]) == (["craters"], "fresh digging")
    assert (stored["source"], stored["model"]) == ("fixtures", None)
    h, w = cv2.imread(str(folder / "image_a.jpg")).shape[:2]
    assert stored["size"] == {"w": w, "h": h}
    assert stored["files"] == {"image_a": "image_a.jpg", "aligned_b": "aligned_b.jpg", "annotated": "annotated.jpg",
                               "source_a": "source_a.jpg", "source_b": "source_b.jpg"}
    assert json.loads((cache / "manifest.json").read_text(encoding="utf-8"))["scenes"] == [scene["id"]]
    assert client.get("/api/demo/scenes").json() == {"scenes": [scene]}


def test_replace_rename_reorder_delete(client, job, cache):
    first = _cache(client, job["job_id"], "First").json()["id"]
    second = _cache(client, job["job_id"], "Second").json()["id"]

    replaced = _cache(client, job["job_id"], "First again", scene_id=first).json()
    assert (replaced["id"], replaced["title"]) == (first, "First again")
    assert _ids(client) == [first, second]  # replaced in place
    assert not list(cache.glob(".*.tmp"))

    renamed = client.patch(f"/api/demo/scenes/{second}", json={"title": " Renamed ", "subtitle": "sub"}).json()
    assert (renamed["title"], renamed["subtitle"]) == ("Renamed", "sub")
    assert client.patch(f"/api/demo/scenes/{second}", json={"title": " "}).status_code == 400

    assert client.put("/api/demo/order", json={"ids": [second, first]}).json() == {"scenes": [second, first]}
    assert _ids(client) == [second, first]
    assert client.put("/api/demo/order", json={"ids": [second]}).status_code == 400
    assert client.put("/api/demo/order", json={"ids": [second, second]}).status_code == 400

    assert client.delete(f"/api/demo/scenes/{second}").json() == {"deleted": second}
    assert _ids(client) == [first] and not (cache / second).exists()
    assert client.delete(f"/api/demo/scenes/{second}").status_code == 404


def test_busy_files_are_retried_and_a_failed_manifest_leaves_no_orphan(client, job, cache, monkeypatch):
    # Windows: a reader (the presentation server, the indexer) holding manifest.json open for a moment.
    real_replace, busy = store.os.replace, [2]

    def flaky_replace(src, dst):
        if Path(dst).name == "manifest.json" and busy[0]:
            busy[0] -= 1
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", flaky_replace)
    monkeypatch.setattr(store, "BUSY_DELAY_S", 0)
    first = _cache(client, job["job_id"], "Busy").json()["id"]
    assert _ids(client) == [first] and busy == [0]

    # Still busy after every retry: the request fails and the new scene's folder is rolled back.
    busy[0] = 10**6
    r = _cache(client, job["job_id"], "Never listed")
    assert r.status_code == 409
    assert sorted(p.name for p in cache.iterdir()) == sorted([first, "manifest.json"])
    assert _ids(client) == [first]


def test_cache_state_rejects_what_cannot_be_presented(client, job):
    assert _cache(client, "0" * 12).status_code == 404  # unknown job
    assert _cache(client, "").status_code == 404
    assert _cache(client, job["job_id"], title="  ").status_code == 400
    assert _cache(client, job["job_id"], scene_id="nope").status_code == 404
    assert client.patch("/api/demo/scenes/nope", json={"title": "x"}).status_code == 404

    running = uuid.uuid4().hex[:12]
    create_job(running, criteria="craters")
    assert _cache(client, running).status_code == 409  # not finished

    pruned = uuid.uuid4().hex[:12]  # finished, but its output folder is gone
    create_job(pruned, criteria="craters")
    complete_job(pruned, job["result"], 0.9, True, "sift", job["images"], {}, [])
    r = _cache(client, pruned)
    assert r.status_code == 409 and "run the analysis again" in r.json()["detail"]
    assert _ids(client) == []
