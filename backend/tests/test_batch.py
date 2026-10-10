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
    settings.set_auto_batch(None)
    batch.worker.resume()


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
    pdf = client.get(f"/api/batches/{d['id']}/report?format=pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF") and len(pdf.content) > 20_000  # four frames + two crops embedded
    assert ".pdf" in pdf.headers["content-disposition"]
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


# --- project batches, automatic batching and the queue ----------------------------------------------

def _drop_days(inbox: Path, project: str, days: dict[int, str]) -> None:
    """Sample stills as <project>_Day<N>.jpg; 'a' / 'b' picks pair01's before / after image."""
    for day, which in days.items():
        shutil.copy(SAMPLES / "pair01" / f"{which}.jpg", inbox / f"{project}_Day{day}.jpg")


def _register(w: watcher.Watcher, inbox: Path, *names: str) -> list[str]:
    return [i for n in names for i in w.register(inbox / n, enqueue=False)]


def test_project_days_form_one_batch_with_one_leg_per_step(batch_env):
    inbox, _ = batch_env
    settings.set_ai_enabled(False)
    _drop_days(inbox, "ProjectX", {1: "a", 2: "b", 5: "a"})
    ids = watcher.run_once(inbox)
    assert len(ids) == 1
    d = store.batch_detail(ids[0])
    assert d["status"] == "done", d["error_message"]
    assert (d["tag_a"], d["tag_b"], d["legs_count"]) == ("Day1", "Day5", 2)
    assert [(leg["tag_a"], leg["tag_b"], leg["status"]) for leg in d["legs"]] == [
        ("Day1", "Day2", "done"), ("Day2", "Day5", "done")]
    assert {(p["leg_idx"], p["tag_a"], p["tag_b"]) for p in d["pairs"]} == {(1, "Day1", "Day2"), (2, "Day2", "Day5")}
    assert [p["idx"] for p in d["pairs"]] == list(range(1, len(d["pairs"]) + 1))  # pair_NN folders stay unique
    legs = client.get(f"/api/batches/{d['id']}/report?format=json").json()["legs"]
    assert [leg["label"] for leg in legs] == ["Day1→Day2", "Day2→Day5"]


def test_new_day_extends_the_finished_project_batch(batch_env):
    inbox, _ = batch_env
    settings.set_ai_enabled(False)
    _drop_days(inbox, "ProjectX", {1: "a", 2: "b"})
    w = watcher.Watcher(inbox)
    [batch_id] = _register(w, inbox, "ProjectX_Day1.jpg", "ProjectX_Day2.jpg")
    batch.process_batch(batch_id)
    first = store.batch_detail(batch_id)["pairs"][0]["findings"][0]
    store.set_review(first["id"], "accepted")

    _drop_days(inbox, "ProjectX", {5: "a"})
    assert _register(w, inbox, "ProjectX_Day5.jpg") == [batch_id]  # same batch, re-opened
    row = store.get_batch(batch_id)
    assert (row["status"], row["tag_b"], row["legs_count"]) == ("queued", "Day5", 2)
    batch.process_batch(batch_id)
    d = store.batch_detail(batch_id)
    assert d["status"] == "done" and [leg["status"] for leg in d["legs"]] == ["done", "done"]
    kept = [f for p in d["pairs"] for f in p["findings"] if f["id"] == first["id"]]
    assert kept and kept[0]["review_status"] == "accepted"
    assert _register(w, inbox, "ProjectX_Day5.jpg") == []  # nothing new
    assert len(store.list_batches()) == 1


def test_stopped_auto_batching_keeps_files_in_the_inbox(batch_env, monkeypatch):
    inbox, submitted = batch_env
    _drop_days(inbox, "ProjectX", {1: "a", 2: "b"})
    w = watcher.Watcher(inbox)
    monkeypatch.setattr(watcher, "_service", w)
    r = client.put("/api/settings", json={"auto_batch": False})
    assert r.json()["auto_batch"] is False and r.json()["ai_enabled"] == settings.ai_enabled()
    assert batch.worker.paused
    assert _register(w, inbox, "ProjectX_Day1.jpg", "ProjectX_Day2.jpg") == []
    assert store.list_batches() == []
    groups = client.get("/api/inbox").json()["groups"]
    assert [(g["site"], g["epochs"], g["batched"]) for g in groups] == [("ProjectX", ["Day1", "Day2"], False)]

    assert client.put("/api/settings", json={"auto_batch": True}).json()["auto_batch"] is True
    assert not batch.worker.paused
    assert len(submitted) == 1 and store.get_batch(submitted[0])["legs_count"] == 1
    assert client.get("/api/inbox").json()["groups"][0]["batched"] is True


def test_clear_queue_only_when_stopped_and_keeps_finished_legs(batch_env, monkeypatch):
    inbox, _ = batch_env
    settings.set_ai_enabled(False)
    _drop_days(inbox, "ProjectX", {1: "a", 2: "b"})
    _drop_days(inbox, "ProjectY", {1: "a", 2: "b"})
    w = watcher.Watcher(inbox)
    monkeypatch.setattr(watcher, "_service", w)
    [x] = _register(w, inbox, "ProjectX_Day1.jpg", "ProjectX_Day2.jpg")
    batch.process_batch(x)
    accepted = store.batch_detail(x)["pairs"][0]["findings"][0]["id"]
    store.set_review(accepted, "accepted")
    _drop_days(inbox, "ProjectX", {5: "a"})
    assert _register(w, inbox, "ProjectX_Day5.jpg") == [x]               # re-opened: queued again
    [y] = _register(w, inbox, "ProjectY_Day1.jpg", "ProjectY_Day2.jpg")  # fresh: queued
    assert client.get("/api/settings").json()["queued_count"] == 2

    assert client.post("/api/queue/clear").status_code == 409           # automatic batching still on
    client.put("/api/settings", json={"auto_batch": False})
    r = client.post("/api/queue/clear")
    assert r.status_code == 200 and r.json()["deleted"] == [y]
    assert set(r.json()["files"]) == {"ProjectX_Day2.jpg", "ProjectX_Day5.jpg", "ProjectY_Day1.jpg", "ProjectY_Day2.jpg"}
    assert store.get_batch(y) is None
    row = store.batch_detail(x)
    assert (row["status"], row["tag_b"], row["legs_count"]) == ("done", "Day2", 1)
    assert any(f["id"] == accepted and f["review_status"] == "accepted" for p in row["pairs"] for f in p["findings"])
    assert client.get("/api/settings").json()["queued_count"] == 0
    assert [g["batched"] for g in client.get("/api/inbox").json()["groups"]] == [False, False]
    batch.process_batch(y)  # a cleared id still in the worker's queue is skipped
    assert store.get_batch(y) is None


def test_inbox_pairs_stay_listed_and_one_can_be_batched_by_hand(batch_env, monkeypatch):
    inbox, submitted = batch_env
    settings.set_ai_enabled(False)
    started: list[str] = []
    monkeypatch.setattr(batch.worker, "run_now", started.append)
    _drop_days(inbox, "ProjectX", {1: "a", 2: "b", 3: "a"})
    w = watcher.Watcher(inbox)
    monkeypatch.setattr(watcher, "_service", w)
    client.put("/api/settings", json={"auto_batch": False})
    assert _register(w, inbox, "ProjectX_Day1.jpg", "ProjectX_Day2.jpg", "ProjectX_Day3.jpg") == []
    pairs = client.get("/api/inbox").json()["pairs"]
    assert [(p["tag_a"], p["tag_b"], p["batched"]) for p in pairs] == [("Day1", "Day2", False), ("Day2", "Day3", False)]

    r = client.post("/api/inbox/batch", json={"name_a": "ProjectX_Day2.jpg", "name_b": "ProjectX_Day3.jpg"})
    assert r.status_code == 200 and r.json()["started"] and started == [r.json()["batch_id"]] and submitted == []
    legs = store.list_legs(started[0])
    assert [(leg["tag_a"], leg["tag_b"]) for leg in legs] == [("Day2", "Day3")]
    pairs = client.get("/api/inbox").json()["pairs"]
    assert [p["batched"] for p in pairs] == [False, True]  # the batched pair stays listed

    batch.process_batch(started[0])
    r = client.post("/api/inbox/batch", json={"name_a": "ProjectX_Day1.jpg", "name_b": "ProjectX_Day2.jpg"})
    assert r.json()["batch_id"] == started[0]  # same project batch, re-opened with the new leg
    assert [p["batched"] for p in client.get("/api/inbox").json()["pairs"]] == [True, True]
    assert client.post("/api/inbox/batch", json={"name_a": "ProjectX_Day1.jpg",
                                                 "name_b": "ProjectX_Day3.jpg"}).status_code == 404  # not consecutive
    assert client.post("/api/inbox/batch", json={"name_a": "nope.jpg", "name_b": "x.jpg"}).status_code == 404


def test_run_now_skips_the_pause(monkeypatch):
    import threading

    ran: list[str] = []
    done = threading.Event()
    monkeypatch.setattr(batch, "process_batch", lambda batch_id: (ran.append(batch_id), done.set()))
    w = batch.BatchWorker()
    w.pause()
    w.submit("auto1")
    w.run_now("manual1")
    assert done.wait(5)
    time.sleep(0.3)
    assert ran == ["manual1"]  # the submitted batch still waits for resume
    done.clear()
    w.resume()
    assert done.wait(5) and ran == ["manual1", "auto1"]


def test_paused_worker_holds_queued_batches(monkeypatch):
    import threading

    ran = threading.Event()
    monkeypatch.setattr(batch, "process_batch", lambda batch_id: ran.set())
    w = batch.BatchWorker()
    w.pause()
    w.submit("b1")
    assert not ran.wait(0.3)
    w.resume()
    assert ran.wait(5)


def test_old_database_gets_one_leg_per_batch(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE batches (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, site TEXT, name_a TEXT,
                name_b TEXT, tag_a TEXT, tag_b TEXT, path_a TEXT, path_b TEXT, kind_a TEXT, kind_b TEXT,
                signature TEXT, ai_enabled INTEGER, status TEXT, stage TEXT, progress TEXT, frames_a INTEGER,
                frames_b INTEGER, matched_pairs INTEGER, pairs_count INTEGER, timings_json TEXT, warnings_json TEXT,
                error_message TEXT);
            CREATE TABLE frame_pairs (id TEXT PRIMARY KEY, batch_id TEXT, idx INTEGER, frame_a INTEGER,
                frame_b INTEGER, time_a REAL, time_b REAL, inliers INTEGER, overlap REAL, ssim REAL,
                align_quality REAL, align_method TEXT, change_ratio REAL, source TEXT, summary TEXT,
                recommendation TEXT, images_json TEXT);
            INSERT INTO batches (id, created_at, site, name_a, name_b, tag_a, tag_b, status, timings_json,
                warnings_json) VALUES ('old1', '2026-01-01', 'Site_A', 'Site_A_Day1.mp4', 'Site_A_Day2.mp4', 'Day1',
                'Day2', 'done', '{}', '[]');
            INSERT INTO frame_pairs (id, batch_id, idx, images_json) VALUES ('p1', 'old1', 1, '{}');
            """
        )
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    store.init_batch_db()
    store.init_batch_db()  # idempotent
    d = store.batch_detail("old1")
    assert d["project"] == "site_a" and d["legs_count"] == 1
    assert [(leg["tag_a"], leg["tag_b"], leg["status"]) for leg in d["legs"]] == [("Day1", "Day2", "done")]
    assert (d["pairs"][0]["leg_idx"], d["pairs"][0]["tag_a"]) == (1, "Day1")
