import json

import numpy as np

from app.analysis import analyze
from app.analysis import gemini_client
from app.analysis.postprocess import clean_box, normalize_confidence, sector_for, to_result
from app.analysis.prompts import build_prompt


def test_analyze_mock_matches_contract():
    img = np.zeros((10, 10, 3), np.uint8)
    r = analyze(img, img, "new tracks")
    assert r.changes and len(r.changes[0].box) == 4


def test_clean_box():
    assert clean_box([100, 200, 300, 400]) == [100, 200, 300, 400]
    assert clean_box([300, 400, 100, 200]) == [100, 200, 300, 400]  # swapped
    assert clean_box([-50, -10, 1200, 1100]) == [0, 0, 1000, 1000]  # clamped
    assert clean_box([100, 100, 102, 300]) is None                  # too thin
    assert clean_box([1, 2, 3]) is None
    assert clean_box(None) is None


def test_sector_for():
    assert sector_for([0, 0, 100, 100]) == "A1"
    assert sector_for([900, 900, 1000, 1000]) == "D4"
    assert sector_for([0, 800, 100, 1000]) == "D1"   # top right
    assert sector_for([400, 300, 500, 400]) == "B2"


def test_normalize_confidence():
    assert normalize_confidence("High") == "high"
    assert normalize_confidence("Vidutinis") == "medium"
    assert normalize_confidence("žemas") == "low"
    assert normalize_confidence("???") == "low"


def test_to_result_drops_malformed():
    r = to_result({
        "summary": "s",
        "recommendation": "r",
        "changes": [
            {"type": "crater", "description": "d", "location_text": "l", "confidence": "high", "box": [10, 10, 200, 200]},
            {"type": "bad", "description": "d", "location_text": "l", "confidence": "high", "box": [1, 2]},
        ],
    })
    assert len(r.changes) == 1 and r.changes[0].sector == "A1"


def test_build_prompt():
    p = build_prompt("new craters", "lt")
    assert "new craters" in p and "Lithuanian" in p


class _FakeModels:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return type("Resp", (), {"parsed": None, "text": payload})()


class _FakeClient:
    def __init__(self, payloads):
        self.models = _FakeModels(payloads)


def test_gemini_client_retries_and_parses(monkeypatch):
    monkeypatch.setattr(gemini_client.time, "sleep", lambda s: None)
    good = json.dumps({
        "summary": "Activity.",
        "recommendation": "Send drone.",
        "changes": [{"type": "tracks", "description": "d", "location_text": "l", "confidence": "medium", "box": [600, 600, 900, 900]}],
    })
    client = _FakeClient([RuntimeError("503"), good])
    img = np.zeros((50, 60, 3), np.uint8)
    r = gemini_client.analyze_with_gemini(img, img, "tracks", client=client)
    assert client.models.calls == 2
    assert r.changes[0].sector == "D4" and r.changes[0].confidence == "medium"
