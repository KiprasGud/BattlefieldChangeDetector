"""Frames from video with FFmpeg at a low fixed rate (default 0.5 fps: one frame every 2 s, never the full 30/60).

FFmpeg decodes by content, so the file extension does not matter, and -noautorotate keeps the stored pixels
(rotation metadata is ignored like EXIF orientation is for stills; alignment handles any rotation).
"""
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FPS = 0.5
DEFAULT_MAX_SIDE = 1920     # frames stay below the 2000 px tiling threshold: at most 2 Gemini calls per pair
FRAME_LIMIT = 900           # 30 min of video at 0.5 fps
TIMEOUT_S = 1800

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


@dataclass(frozen=True)
class Frame:
    index: int          # 0-based position in the extracted sequence
    t: float            # seconds into the source; display only, never used to match frames
    path: Path


def frame_fps() -> float:
    return float(os.getenv("FRAME_FPS") or DEFAULT_FPS)


def frame_max_side() -> int:
    return int(os.getenv("FRAME_MAX_SIDE") or DEFAULT_MAX_SIDE)


def ffmpeg_exe() -> str:
    """FFMPEG_BIN, else ffmpeg on PATH, else the binary bundled with the imageio-ffmpeg wheel."""
    exe = os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError("FFmpeg not found: pip install imageio-ffmpeg, put ffmpeg on PATH or set FFMPEG_BIN") from e


def extract_frames(path, out_dir, fps: float = 0.0, max_side: int = 0, limit: int = FRAME_LIMIT) -> list[Frame]:
    """Write frames of `path` to out_dir as JPEG (long side <= max_side) and list them in order.
    Raises ValueError when FFmpeg finds no video stream (not a video, or a corrupt file)."""
    fps = fps or frame_fps()
    max_side = max_side or frame_max_side()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = f"scale=w='min({max_side},iw)':h='min({max_side},ih)':force_original_aspect_ratio=decrease"
    cmd = [
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-noautorotate", "-i", str(path),
        "-map", "0:v:0", "-vf", f"fps={fps},{scale}", "-frames:v", str(limit), "-q:v", "2",
        str(out_dir / "%05d.jpg"),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=TIMEOUT_S, **_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"FFmpeg timed out after {TIMEOUT_S} s on {Path(path).name}") from e
    files = sorted(out_dir.glob("*.jpg"))
    if not files:
        lines = (proc.stderr or "").strip().splitlines()
        detail = lines[-1] if lines else f"exit code {proc.returncode}"
        raise ValueError(f"{Path(path).name}: not a readable image or video ({detail})")
    return [Frame(i, i / fps, f) for i, f in enumerate(files)]
