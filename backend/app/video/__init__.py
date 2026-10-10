"""Video support: FFmpeg frame extraction and cross-flight frame matching."""
from .extract import FRAME_LIMIT, Frame, extract_frames, ffmpeg_exe, frame_fps, frame_max_side
from .match import MatchedPair, describe, footprint_overlap, match_flights

__all__ = [
    "FRAME_LIMIT", "Frame", "MatchedPair", "describe", "extract_frames", "ffmpeg_exe", "footprint_overlap",
    "frame_fps", "frame_max_side", "match_flights",
]
