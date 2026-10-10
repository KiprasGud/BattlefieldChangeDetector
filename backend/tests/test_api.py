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
