import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _jpg():
    ok, buf = cv2.imencode(".jpg", np.zeros((100, 120, 3), np.uint8))
    return buf.tobytes()


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_analyze_stub():
    r = client.post(
        "/api/analyze",
        files={"image_a": ("a.jpg", _jpg(), "image/jpeg"), "image_b": ("b.jpg", _jpg(), "image/jpeg")},
        data={"criteria": "new tracks"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["changes"]
    assert body["images"]["annotated_url"].startswith("/api/files/")
    assert body["images"]["aligned_b_url"].startswith("/api/files/")
    assert body["images"]["image_a_url"].startswith("/api/files/")


def test_analyze_with_grid():
    r = client.post(
        "/api/analyze",
        files={"image_a": ("a.jpg", _jpg(), "image/jpeg"), "image_b": ("b.jpg", _jpg(), "image/jpeg")},
        data={"criteria": "new tracks", "draw_grid": "true"},
    )
    assert r.status_code == 200
    assert r.json()["images"]["annotated_url"]


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


def test_analyze_corrupt_image_error():
    r = client.post(
        "/api/analyze",
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
