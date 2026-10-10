"""Watch-folder batches end to end: name-paired media -> matched frame pairs -> findings -> review -> report."""
import shutil
import time
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import batch, settings
from app.contracts import AnalysisResult, Change
from app.ingest import watcher
from app.main import app
from app.storage import batches as store
from app.storage import db

SAMPLES = Path(__file__).resolve().parents[2] / "shared" / "sample_data"
CHANGE = (1000, 120, 1060, 180)  # x0, y0, x1, y1 in world pixels: a new object painted into flight B's world

client = TestClient(app)


@pytest.fixture
def batch_env(tmp_path, monkeypatch):
    """Batches in a throwaway database and output folder; nothing runs on the background worker."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(batch, "BATCH_DIR", tmp_path / "batches")
    submitted: list[str] = []
    monkeypatch.setattr(batch.worker, "submit", submitted.append)
    store.init_batch_db()
    inbox = tmp_path / "input"
    inbox.mkdir()
    yield inbox, submitted
    settings.set_ai_enabled(None)


def _drop_stills(inbox: Path, after_name: str = "Spot_After.png") -> None:
    shutil.copy(SAMPLES / "pair01" / "a.jpg", inbox / "Spot_Before.jpg")
    shutil.copy(SAMPLES / "pair01" / "b.jpg", inbox / after_name)  # JPEG bytes: the extension is irrelevant


def _run_stills(inbox: Path) -> dict:
    _drop_stills(inbox)
    ids = watcher.run_once(inbox)
    assert len(ids) == 1
    return store.batch_detail(ids[0])


def _inside(point, polygon) -> bool:
    return cv2.pointPolygonTest(polygon, (float(point[0]), float(point[1])), False) >= 0


def test_video_flights_end_to_end_cv_only(batch_env, flights):
    inbox, _ = batch_env
    settings.set_ai_enabled(False)
    world_b = flights.world("b")
    cv2.rectangle(world_b, CHANGE[:2], CHANGE[2:], (255, 0, 255), -1)
    flight_a, flight_b = flights.flight_a(), flights.flight_b(world=world_b)
    flights.write_video(inbox / "Site_T_Day1.avi", [f for f, _ in flight_a])
    flights.write_video(inbox / "Site_T_Day2.dat", [f for f, _ in flight_b])  # extension says nothing

    ids = watcher.run_once(inbox)
    assert len(ids) == 1
    d = store.batch_detail(ids[0])
    assert d["status"] == "done", d["error_message"]
    assert (d["kind_a"], d["kind_b"]) == ("video", "video")
    assert (d["frames_a"], d["frames_b"]) == (len(flight_a), len(flight_b))
    assert d["matched_pairs"] >= 3 and d["pairs"]
    assert all(p["source"] == "cv" for p in d["pairs"])
    findings = [f for p in d["pairs"] for f in p["findings"]]
    assert all(f["category"] == "unknown_anomaly" and f["review_status"] == "pending" for f in findings)

    corners = [(CHANGE[0], CHANGE[1]), (CHANGE[2], CHANGE[1]), (CHANGE[2], CHANGE[3]), (CHANGE[0], CHANGE[3])]
    seen = 0
    for p in d["pairs"]:
        fp_a, fp_b = flight_a[p["frame_a"]][1], flight_b[p["frame_b"]][1]
        if not all(_inside(c, fp_a) and _inside(c, fp_b) for c in corners):
            continue
        seen += 1
        w, h = flights.SIZE  # A frames are axis-aligned at scale 1: frame = world - top-left corner
        cx = ((CHANGE[0] + CHANGE[2]) / 2 - fp_a[0][0]) / w * 1000
        cy = ((CHANGE[1] + CHANGE[3]) / 2 - fp_a[0][1]) / h * 1000
        assert any(f["box"][0] <= cy <= f["box"][2] and f["box"][1] <= cx <= f["box"][3] for f in p["findings"])
    assert seen >= 1, "no curated pair shows the painted change in both frames"

    assert watcher.run_once(inbox) == []  # same content again: nothing new to process


def test_review_and_report(batch_env):
    inbox, _ = batch_env
    settings.set_ai_enabled(False)
    d = _run_stills(inbox)
    assert (d["kind_a"], d["kind_b"]) == ("image", "image") and len(d["pairs"]) == 1
    findings = d["pairs"][0]["findings"]
    assert len(findings) == 2  # the two real changes of pair01

    listed = client.get("/api/batches").json()
    assert listed[0]["id"] == d["id"] and listed[0]["pending_count"] == 2
    keep, drop = findings
    r = client.post(f"/api/findings/{keep['id']}/review", json={"status": "accepted"})
    assert r.status_code == 200 and r.json()["review_status"] == "accepted" and r.json()["reviewed_at"]
    assert client.post(f"/api/findings/{drop['id']}/review", json={"status": "rejected"}).status_code == 200
    assert client.post(f"/api/findings/{drop['id']}/review", json={"status": "maybe"}).status_code == 422
    assert client.post("/api/findings/nope/review", json={"status": "accepted"}).status_code == 404

    detail = client.get(f"/api/batches/{d['id']}").json()
    assert detail["accepted_count"] == 1 and detail["rejected_count"] == 1
    report = client.get(f"/api/batches/{d['id']}/report?format=json")
    assert "attachment" in report.headers["content-disposition"]
    changes = report.json()["verified_changes"]
    assert [c["box"] for c in changes] == [keep["box"]]
    assert report.json()["totals"]["Unknown Anomaly"] == 1
    page = client.get(f"/api/batches/{d['id']}/report?format=html")
    assert page.status_code == 200 and "VERIFIED CHANGE REPORT" in page.text
    assert page.text.count("data:image/jpeg;base64,") == 3  # annotated frame + before/after crop
    assert client.get("/api/batches/nope").status_code == 404


def test_ai_requested_without_key_falls_back_to_cv(batch_env):
    inbox, _ = batch_env
    settings.set_ai_enabled(True)  # MOCK_LLM=1 in tests: no real model available
    d = _run_stills(inbox)
    assert d["ai_enabled"] is True
    assert any("AI requested but unavailable" in w for w in d["warnings"])
    assert d["pairs"][0]["source"] == "cv"


def _fake_gemini(calls):
    def analyze(img_a, aligned_b, criteria, lang="en", hints=None, aligned=True):
        calls.append((criteria, hints))
        return AnalysisResult(report_date=date.today().isoformat(), summary="One new structure.", recommendation="Check.",
                              changes=[Change(type="bunker", description="new roof", location_text="centre",
                                              confidence="high", box=[400, 300, 600, 420], sector="B2",
                                              category="new_structure")])
    return analyze


def test_ai_findings_keep_their_category(batch_env, monkeypatch):
    inbox, _ = batch_env
    calls = []
    monkeypatch.setattr(batch, "use_mock", lambda: False)
    monkeypatch.setattr(batch, "analyze", _fake_gemini(calls))
    settings.set_ai_enabled(True)
    d = _run_stills(inbox)
    assert len(calls) == 1 and calls[0][0] == batch.batch_criteria() and calls[0][1]  # heatmap hints passed
    pair = d["pairs"][0]
    assert pair["source"] == "ai" and pair["summary"] == "One new structure."
    assert [(f["category"], f["type"]) for f in pair["findings"]] == [("new_structure", "bunker")]


def test_gemini_failure_keeps_cv_regions(batch_env, monkeypatch):
    inbox, _ = batch_env

    def broken(*args, **kwargs):
        raise RuntimeError("503 overloaded")

    monkeypatch.setattr(batch, "use_mock", lambda: False)
    monkeypatch.setattr(batch, "analyze", broken)
    settings.set_ai_enabled(True)
    d = _run_stills(inbox)
    assert d["status"] == "done" and d["pairs"][0]["source"] == "cv"
    assert any("Gemini failed" in w for w in d["warnings"])


def test_failed_full_alignment_uses_matching_homography(batch_env, monkeypatch):
    from app.contracts import AlignResult

    inbox, _ = batch_env
    settings.set_ai_enabled(False)
    monkeypatch.setattr(batch, "align", lambda a, b: AlignResult(aligned_b=b, ok=False))
    d = _run_stills(inbox)
    assert len(d["pairs"]) == 1 and len(d["pairs"][0]["findings"]) == 2  # same regions as a full alignment
    assert any("used the frame-matching homography" in w for w in d["warnings"])


def test_settings_toggle_and_rerun(batch_env):
    inbox, submitted = batch_env
    assert client.put("/api/settings", json={"ai_enabled": False}).json()["ai_enabled"] is False
    assert client.get("/api/settings").json()["ai_enabled"] is False
    d = _run_stills(inbox)
    assert d["ai_enabled"] is False

    client.put("/api/settings", json={"ai_enabled": True})
    r = client.post(f"/api/batches/{d['id']}/rerun")
    assert r.status_code == 200
    new_id = r.json()["batch_id"]
    assert submitted == [new_id]
    rerun = store.get_batch(new_id)
    assert rerun["ai_enabled"] is True and rerun["status"] == "queued" and rerun["signature"] == d["signature"]

    (inbox / "Spot_After.png").unlink()
    assert client.post(f"/api/batches/{d['id']}/rerun").status_code == 409
    assert client.post("/api/batches/nope/rerun").status_code == 404


def test_watcher_waits_for_copies_to_settle(batch_env):
    inbox, submitted = batch_env
    _drop_stills(inbox, "Spot_After.jpg")
    (inbox / ".hidden_Day1.mp4").write_bytes(b"x")
    w = watcher.Watcher(inbox)
    for path in inbox.iterdir():
        w.touch(path)
    t0 = time.monotonic()
    assert w.settle(t0) == []          # events too recent
    assert w.settle(t0 + 3) == []      # first quiet poll: remember size and mtime
    ids = w.settle(t0 + 4)             # unchanged since: finished copying -> paired -> queued
    assert len(ids) == 1 and submitted == ids
    snap = w.inbox.snapshot()
    assert snap["paired"] == ["Spot_After.jpg", "Spot_Before.jpg"] and snap["rejected"] == []


def test_interrupted_batches_resume(batch_env):
    inbox, submitted = batch_env
    _drop_stills(inbox)
    w = watcher.Watcher(inbox)
    ids = [i for p in sorted(inbox.iterdir()) for i in w.register(p, enqueue=False)]
    store.update_batch(ids[0], status="running", stage="matching")
    assert batch.resume_interrupted() == ids and submitted == ids
    assert store.get_batch(ids[0])["status"] == "queued"


def test_analyze_endpoint_respects_ai_toggle(batch_env):
    def jpg(path):
        return cv2.imencode(".jpg", cv2.imread(str(path)))[1].tobytes()

    settings.set_ai_enabled(False)
    r = client.post(
        "/api/analyze?sync=true",
        files={"image_a": ("a.jpg", jpg(SAMPLES / "pair01" / "a.jpg"), "image/jpeg"),
               "image_b": ("b.jpg", jpg(SAMPLES / "pair01" / "b.jpg"), "image/jpeg")},
        data={"criteria": "anything"},
    )
    assert r.status_code == 200
    body = r.json()
    assert any("AI step disabled" in w for w in body["warnings"])
    assert body["result"]["changes"] == []  # OpenCV only aligns: no AI, no detections
    assert "heatmap_url" in body["images"]  # the heatmap is still drawn as a visual aid
