import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.analysis import analyze
from app.analysis import cache, gemini_client, tiling
from app.analysis.postprocess import clean_box, normalize_confidence, sector_for, to_result
from app.analysis.prompts import build_prompt

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "shared" / "sample_data"


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
        self.requests = []  # (model, contents, config) per call

    def generate_content(self, model, contents, config):
        self.calls += 1
        self.requests.append((model, contents, config))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return type("Resp", (), {"parsed": None, "text": payload})()


class _FakeClient:
    def __init__(self, payloads):
        self.models = _FakeModels(payloads)


def _llm_json(*boxes):
    return json.dumps({
        "summary": "Activity.",
        "recommendation": "Send drone.",
        "changes": [{"type": "tracks", "description": "d", "location_text": "l", "confidence": "medium", "box": b} for b in boxes],
    })


def test_gemini_client_retries_and_parses(monkeypatch):
    monkeypatch.setattr(gemini_client.time, "sleep", lambda s: None)
    client = _FakeClient([RuntimeError("503"), _llm_json([600, 600, 900, 900])])
    img = np.zeros((50, 60, 3), np.uint8)
    r = gemini_client.analyze_with_gemini(img, img, "tracks", client=client, verify=False)
    assert client.models.calls == 2
    assert r.changes[0].sector == "D4" and r.changes[0].confidence == "medium"


def test_verification_drops_rejected():
    verdicts = json.dumps({"verdicts": [
        {"index": 1, "real": True, "matches_criteria": True, "reason": "ok"},
        {"index": 2, "real": False, "matches_criteria": True, "reason": "shadow"},
    ]})
    client = _FakeClient([_llm_json([0, 0, 200, 200], [600, 600, 900, 900]), verdicts])
    img = np.full((100, 100, 3), 120, np.uint8)
    r = gemini_client.analyze_with_gemini(img, img, "tracks", client=client, verify=True)
    assert client.models.calls == 2
    assert [c.box for c in r.changes] == [[0, 0, 200, 200]]


def test_verification_failure_keeps_detections(monkeypatch):
    monkeypatch.setattr(gemini_client.time, "sleep", lambda s: None)
    client = _FakeClient([_llm_json([0, 0, 200, 200]), RuntimeError("x"), RuntimeError("x"), RuntimeError("x")])
    img = np.full((100, 100, 3), 120, np.uint8)
    r = gemini_client.analyze_with_gemini(img, img, "tracks", client=client, verify=True)
    assert len(r.changes) == 1


def test_boxes_on_black_border_dropped():
    img = np.full((100, 100, 3), 120, np.uint8)
    img[:, 80:] = 0  # warp border on the right
    raw = json.loads(_llm_json([0, 850, 300, 1000], [0, 0, 300, 300]))
    r = to_result(raw, image_b=img)
    assert [c.box for c in r.changes] == [[0, 0, 300, 300]]


def test_prompt_lists_hints_and_black_area():
    p = build_prompt("tracks", "en", hints=[[10, 20, 30, 40]])
    assert "[10, 20, 30, 40]" in p and "Pure black" in p
    assert "CANDIDATE" not in build_prompt("tracks", "en")


def test_prompt_states_alignment_status():
    assert "already geometrically aligned" in build_prompt("tracks", "en")
    unaligned = build_prompt("tracks", "en", aligned=False)
    assert "alignment FAILED" in unaligned and "already geometrically aligned" not in unaligned


# --- Gemini 3.5 Flash-Lite request shape and failure policy ---------------------------------------

def _image_parts(contents):
    return [p for p in contents if not isinstance(p, str)]


def test_default_model_request_shape(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    client = _FakeClient([_llm_json([0, 0, 200, 200])])
    img = np.full((100, 100, 3), 120, np.uint8)
    gemini_client.analyze_with_gemini(img, img, "tracks", client=client, verify=False)
    model, contents, config = client.models.requests[0]
    assert model == "gemini-3.5-flash-lite"
    assert config.temperature is None  # deprecated on Gemini 3.x
    assert config.thinking_config.thinking_level.value == "MINIMAL"
    parts = _image_parts(contents)
    assert len(parts) == 2 and all(p.media_resolution.level.value == "MEDIA_RESOLUTION_HIGH" for p in parts)


def test_legacy_model_keeps_temperature(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    client = _FakeClient([_llm_json([0, 0, 200, 200])])
    img = np.full((100, 100, 3), 120, np.uint8)
    gemini_client.analyze_with_gemini(img, img, "tracks", client=client, verify=False)
    _, contents, config = client.models.requests[0]
    assert config.temperature == 0.2 and config.thinking_config is None
    assert all(p.media_resolution is None for p in _image_parts(contents))


def test_client_error_is_not_retried(monkeypatch):
    from google.genai import errors
    monkeypatch.setattr(gemini_client.time, "sleep", lambda s: None)
    missing = errors.ClientError(404, {"error": {"code": 404, "message": "model not found", "status": "NOT_FOUND"}})
    client = _FakeClient([missing, _llm_json([0, 0, 200, 200])])
    img = np.full((100, 100, 3), 120, np.uint8)
    with pytest.raises(gemini_client.GeminiError, match="404"):
        gemini_client.analyze_with_gemini(img, img, "tracks", client=client, verify=False)
    assert client.models.calls == 1


def test_server_error_is_retried(monkeypatch):
    from google.genai import errors
    monkeypatch.setattr(gemini_client.time, "sleep", lambda s: None)
    busy = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    client = _FakeClient([busy, _llm_json([0, 0, 200, 200])])
    img = np.full((100, 100, 3), 120, np.uint8)
    r = gemini_client.analyze_with_gemini(img, img, "tracks", client=client, verify=False)
    assert client.models.calls == 2 and len(r.changes) == 1


def test_tiled_analysis_verifies_once(monkeypatch):
    import app.analysis as analysis_pkg
    for k, v in {"MOCK_LLM": "0", "GEMINI_API_KEY": "test", "ANALYSIS_CACHE": "0", "ANALYSIS_VERIFY": "1",
                 "ANALYSIS_TILING": "1", "ANALYSIS_TILE_MIN_SIDE": "100", "ANALYSIS_TILE_GRID": "4"}.items():
        monkeypatch.setenv(k, v)
    verdicts = json.dumps({"verdicts": [{"index": 1, "real": True, "matches_criteria": True, "reason": "ok"}]})
    client = _FakeClient([_llm_json([100, 100, 300, 300])] * 17 + [verdicts])
    monkeypatch.setattr(analysis_pkg, "make_client", lambda: client)
    img = np.full((400, 400, 3), 120, np.uint8)
    analyze(img, img, "tracks")
    requests = client.models.requests
    assert len(requests) == 1 + 16 + 1  # full image + 4x4 tiles + one verification (was one per tile)
    assert requests[-1][2].response_schema is gemini_client.LLMVerification


# --- mock fixtures -------------------------------------------------------------------------------

def _sample(pair, name="a"):
    return cv2.imread(str(SAMPLES / pair / f"{name}.jpg"))


def test_mock_pair01_boxes_follow_criteria():
    a = _sample("pair01")
    both = analyze(a, _sample("pair01", "b"), "New vehicle tracks, craters / digging")
    assert {c.sector for c in both.changes} == {"D1", "B3"}
    tracks = analyze(a, a, "New vehicle tracks")
    assert len(tracks.changes) == 1 and tracks.changes[0].sector == "D1"
    none = analyze(a, a, "Felled trees")
    assert none.changes == [] and none.summary


def test_mock_lithuanian_and_unknown_criteria():
    a = _sample("pair02")
    lt = analyze(a, a, "Nuvirtę medžiai", "lt")
    assert len(lt.changes) == 1 and "medis" in lt.changes[0].type
    everything = analyze(a, a, "anything unusual")
    assert len(everything.changes) == 2


def test_mock_unknown_image_uses_generic_fixture():
    img = np.random.default_rng(0).integers(0, 255, (60, 80, 3), dtype=np.uint8)
    assert analyze(img, img, "tracks").changes


def _expected_box(box, T, src_shape, dst_shape):
    """Fixture box (0-1000, sample frame) carried through the known transform T, clipped to the new frame."""
    h, w = src_shape[:2]
    hd, wd = dst_shape[:2]
    y0, x0, y1, x1 = (v / 1000 for v in box)
    p = T @ np.array([[x0 * w, x1 * w, x1 * w, x0 * w], [y0 * h, y0 * h, y1 * h, y1 * h], [1, 1, 1, 1]])
    xs, ys = np.clip(p[0] / p[2], 0, wd), np.clip(p[1] / p[2], 0, hd)
    return [ys.min() / hd * 1000, xs.min() / wd * 1000, ys.max() / hd * 1000, xs.max() / wd * 1000]


@pytest.mark.parametrize("kind", ["hflip", "rot90", "crop10", "scale0.5", "bright"])
def test_mock_recognizes_transformed_sample(kind, transform):
    a = _sample("pair01")
    moved, T = transform(a, kind)
    r = analyze(moved, moved, "New vehicle tracks, craters / digging")
    fixture = json.loads((ROOT / "shared" / "fixtures" / "pair01.json").read_text(encoding="utf-8"))
    expected = [_expected_box(c["box"], T, a.shape, moved.shape) for c in fixture["changes"]]
    assert len(r.changes) == len(expected)
    for want in expected:
        assert max(tiling.iou(c.box, want) for c in r.changes) >= 0.7


# --- tiling + cache ------------------------------------------------------------------------------

def test_tile_box_roundtrip():
    tiles = tiling.make_tiles(2000, 3000, 4)
    assert len(tiles) == 16
    tile = tiles[5]
    full = [400, 400, 450, 450]
    local = tiling.full_box_to_tile(full, tile, 2000, 3000)
    back = tiling.tile_box_to_full(local, tile, 2000, 3000)
    assert all(abs(x - y) <= 2 for x, y in zip(back, full))


def test_nms_keeps_most_confident():
    from app.contracts import Change
    mk = lambda box, conf: Change(type="t", description="", location_text="", confidence=conf, box=box)
    kept = tiling.nms([mk([0, 0, 100, 100], "low"), mk([5, 5, 100, 100], "high"), mk([500, 500, 600, 600], "low")])
    assert [c.confidence for c in kept] == ["high", "low"] and len(kept) == 2


def test_analyze_tiled_maps_boxes_back():
    calls = []

    def fake(img_a, img_b, criteria, lang, hints):
        calls.append(img_a.shape)
        return to_result(json.loads(_llm_json([0, 0, 500, 500])))

    img = np.full((400, 400, 3), 100, np.uint8)
    r = tiling.analyze_tiled(img, img, "x", "en", None, fake)
    assert len(calls) == 1 + 16
    assert all(0 <= v <= 1000 for c in r.changes for v in c.box)
    assert any(c.box == [0, 0, 500, 500] for c in r.changes)


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYSIS_CACHE_DIR", str(tmp_path))
    img = np.zeros((10, 10, 3), np.uint8)
    key = cache.make_key(img, img, "tracks", "en", [[1, 2, 3, 4]], {"model": "m"})
    assert key != cache.make_key(img, img, "craters", "en", None, {"model": "m"})
    assert cache.get(key) is None
    result = to_result(json.loads(_llm_json([0, 0, 100, 100])))
    cache.put(key, result)
    assert cache.get(key).changes == result.changes


def test_eval_metrics():
    sys.path.insert(0, str(ROOT / "eval"))
    from metrics import match, summarize
    c = match([[0, 0, 100, 100], [500, 500, 600, 600]], [[0, 0, 110, 110]])
    assert (c["tp"], c["fp"], c["fn"]) == (1, 1, 0)
    s = summarize([c, match([], [[0, 0, 10, 10]])])
    assert s["precision"] == 0.5 and abs(s["recall"] - 0.5) < 1e-9
