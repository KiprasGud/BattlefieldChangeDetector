import time
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
SAMPLES = Path(__file__).resolve().parents[2] / "shared" / "sample_data"


def _jpg(img=None):
    ok, buf = cv2.imencode(".jpg", np.zeros((100, 120, 3), np.uint8) if img is None else img)
    return buf.tobytes()


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_analyze_async_job_flow():
    # 1. Post analysis job
    r = client.post(
        "/api/analyze",
        files={"image_a": ("a.jpg", _jpg(), "image/jpeg"), "image_b": ("b.jpg", _jpg(), "image/jpeg")},
        data={"criteria": "new tracks", "draw_grid": "true"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    job_id = body["job_id"]
    assert body["status"] in ("queued", "running", "done")

    # 2. Poll job status until done (timeout 10s)
    deadline = time.time() + 10.0
    completed_job = None
    while time.time() < deadline:
        res = client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 200
        data = res.json()
        if data["status"] in ("done", "error"):
            completed_job = data
            break
        time.sleep(0.05)

    assert completed_job is not None, "Job did not complete within timeout"
    assert completed_job["status"] == "done"
    assert completed_job["stage"] == "done"
    assert completed_job["result"]["changes"]
    assert completed_job["images"]["annotated_url"].startswith("/api/files/")
    assert completed_job["images"]["aligned_b_url"].startswith("/api/files/")
    assert completed_job["images"]["image_a_url"].startswith("/api/files/")
    assert "align" in completed_job["timings"]
    assert "ai" in completed_job["timings"]
    assert "render" in completed_job["timings"]


def test_analyze_sync_mode():
    r = client.post(
        "/api/analyze?sync=true",
        files={"image_a": ("a.jpg", _jpg(), "image/jpeg"), "image_b": ("b.jpg", _jpg(), "image/jpeg")},
        data={"criteria": "new tracks"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["changes"]
    assert body["images"]["annotated_url"].startswith("/api/files/")
    assert "total" in body["timings"]


def test_analyze_matches_mirrored_rotated_recon():
    a = cv2.imread(str(SAMPLES / "pair01" / "a.jpg"))
    b = cv2.rotate(cv2.flip(cv2.imread(str(SAMPLES / "pair01" / "b.jpg")), 1), cv2.ROTATE_90_CLOCKWISE)
    r = client.post(
        "/api/analyze?sync=true",
        # Mismatched file name / type on purpose: only decoded pixels count.
        files={"image_a": ("a.jpg", _jpg(a), "image/jpeg"), "image_b": ("b.png", _jpg(b), "image/jpeg")},
        data={"criteria": "New vehicle tracks, craters / digging"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["align_ok"] is True
    assert any("mirrored" in w for w in body["warnings"])
    assert {c["sector"] for c in body["result"]["changes"]} == {"D1", "B3"}


def test_get_jobs_history():
    r = client.get("/api/jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert isinstance(jobs, list)
    assert len(jobs) >= 1
    first_job = jobs[0]
    assert "job_id" in first_job
    assert "status" in first_job
    assert "criteria" in first_job


def test_get_job_not_found():
    r = client.get("/api/jobs/nonexistent-id")
    assert r.status_code == 404


def test_analyze_empty_criteria_error():
    r = client.post(
        "/api/analyze",
        files={"image_a": ("a.jpg", _jpg(), "image/jpeg"), "image_b": ("b.jpg", _jpg(), "image/jpeg")},
        data={"criteria": "   "},
    )
    assert r.status_code == 400
    assert "criteria" in r.text.lower()


def test_analyze_invalid_lang_error():
    r = client.post(
        "/api/analyze",
        files={"image_a": ("a.jpg", _jpg(), "image/jpeg"), "image_b": ("b.jpg", _jpg(), "image/jpeg")},
        data={"criteria": "tracks", "lang": "de"},
    )
    assert r.status_code == 400
    assert "language" in r.text.lower()


def test_analyze_corrupt_image_sync_error():
    r = client.post(
        "/api/analyze?sync=true",
        files={"image_a": ("a.jpg", b"not-an-image", "image/jpeg"), "image_b": ("b.jpg", _jpg(), "image/jpeg")},
        data={"criteria": "tracks"},
    )
    assert r.status_code == 400


def test_get_samples():
    r = client.get("/api/samples")
    assert r.status_code == 200
    samples = r.json()
    assert isinstance(samples, list)
    assert len(samples) >= 1
    sample01 = next((s for s in samples if s["id"] == "pair01"), None)
    assert sample01 is not None
    assert "image_a_url" in sample01
    assert "criteria" in sample01


def test_get_sample_file():
    r = client.get("/api/samples/pair01/a.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 0


def test_get_sample_file_not_found():
    r = client.get("/api/samples/nonexistent/a.jpg")
    assert r.status_code == 404
