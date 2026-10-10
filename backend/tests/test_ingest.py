"""Name pairing, content-based media detection and FFmpeg frame extraction."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.ingest import Inbox, media_kind, pairs_for, parse_name
from app.ingest.naming import logical_name
from app.video import extract_frames


# --- naming ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,key,tag", [
    ("Site_A_Day1.mp4", "Site_A", "Day1"),
    ("ProjectX_Before.jpg", "ProjectX", "Before"),
    ("projectx_AFTER", "projectx", "AFTER"),              # no extension at all
    ("Site_A_Day12.final.mov", "Site_A", "Day12"),       # everything after the first dot is ignored
])
def test_parse_name(name, key, tag):
    m = parse_name(Path(name))
    assert (m.key, m.tag) == (key, tag)


@pytest.mark.parametrize("name", ["SiteA.mp4", "Site_A_Day.mp4", "Site_A_Final.jpg", "_Day1.mp4", "Day1.mp4"])
def test_parse_name_rejects_other_schemes(name):
    assert parse_name(Path(name)) is None


def test_extension_is_ignored():
    assert logical_name("Site_A_Day1.mp4") == logical_name("Site_A_Day1.MOV") == logical_name("Site_A_Day1")


def test_pairs_follow_epoch_order_not_listing_order():
    names = ["S_Day10.mp4", "S_After.jpg", "S_Day2.mp4", "S_Before.png", "S_Day1.mov"]
    pairs = pairs_for([parse_name(Path(n)) for n in names])
    assert [(a.tag, b.tag) for a, b in pairs] == [
        ("Before", "Day1"), ("Day1", "Day2"), ("Day2", "Day10"), ("Day10", "After"),
    ]


def test_inbox_pairs_by_name_and_rejects_conflicts(tmp_path):
    inbox = Inbox()
    assert [m.tag for m in inbox.add(tmp_path / "Site_A_Day1.mp4")] == ["Day1"]  # alone: nothing to batch yet
    assert inbox.snapshot()["waiting"] == ["Site_A_Day1.mp4"]
    group = inbox.add(tmp_path / "site_a_day2.MOV")  # site keys ignore letter case
    assert [m.path.name for m in group] == ["Site_A_Day1.mp4", "site_a_day2.MOV"]
    assert inbox.add(tmp_path / "Site_A_Day1.jpg") == []  # same site and epoch, other extension
    assert inbox.add(tmp_path / "notes.txt") == []
    snap = inbox.snapshot()
    assert snap["waiting"] == [] and sorted(snap["paired"]) == ["Site_A_Day1.mp4", "site_a_day2.MOV"]
    assert {r["name"] for r in snap["rejected"]} == {"Site_A_Day1.jpg", "notes.txt"}
    inbox.remove(tmp_path / "Site_A_Day1.mp4")
    assert inbox.snapshot()["waiting"] == ["site_a_day2.MOV"]


def test_inbox_groups_whole_projects_in_epoch_order(tmp_path):
    inbox = Inbox()
    for name in ("X_Day5.mp4", "X_Day1.mp4", "Y_Before.jpg", "X_Day2.mp4"):
        inbox.add(tmp_path / name)
    assert [[m.tag for m in g] for g in inbox.groups()] == [["Day1", "Day2", "Day5"]]  # Y has no partner yet
    assert [m.tag for m in inbox.add(tmp_path / "Y_After.jpg")] == ["Before", "After"]
    assert len(inbox.groups()) == 2


# --- media kind by content --------------------------------------------------------------------------

def _gradient(w=320, h=240, shade=0):
    img = np.empty((h, w, 3), np.uint8)
    img[..., 0] = shade
    img[..., 1] = (np.arange(w) % 256)[None, :]
    img[..., 2] = 128
    return img


def test_media_kind_reads_content_not_extension(tmp_path, flights):
    jpeg = tmp_path / "still.mp4"
    jpeg.write_bytes(cv2.imencode(".jpg", _gradient())[1].tobytes())
    png = tmp_path / "still.avi"
    png.write_bytes(cv2.imencode(".png", _gradient())[1].tobytes())
    video = flights.write_video(tmp_path / "clip.jpg", [_gradient(shade=s) for s in (0, 100)])
    assert media_kind(jpeg) == "image" and media_kind(png) == "image"
    assert media_kind(video) == "video"


def test_unreadable_media_is_reported(tmp_path):
    junk = tmp_path / "Site_Z_Day1.mp4"
    junk.write_bytes(np.random.default_rng(0).integers(0, 255, 5000, dtype=np.uint8).tobytes())
    with pytest.raises(ValueError, match="not a readable image or video"):
        extract_frames(junk, tmp_path / "frames")


# --- FFmpeg extraction ----------------------------------------------------------------------------

def test_extracts_one_frame_every_two_seconds(tmp_path, flights):
    shades = [0, 30, 60, 90, 120, 150, 180, 210]
    # 16 s of video at 4 fps (each shade held for 2 s): 64 decoded frames, 8 extracted
    video = flights.write_video(tmp_path / "flight.dat", [_gradient(shade=s) for s in shades for _ in range(8)], fps=4)
    frames = extract_frames(video, tmp_path / "frames")
    assert [f.t for f in frames] == [0, 2, 4, 6, 8, 10, 12, 14]
    got = [int(cv2.imread(str(f.path))[5, 5, 0]) for f in frames]
    assert all(abs(g - s) <= 6 for g, s in zip(got, shades))


def test_extraction_caps_frame_size(tmp_path, flights):
    video = flights.write_video(tmp_path / "big.avi", [_gradient(800, 600)] * 2)
    frames = extract_frames(video, tmp_path / "frames", max_side=400)
    assert cv2.imread(str(frames[0].path)).shape[:2] == (300, 400)
