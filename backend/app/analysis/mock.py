import json
from pathlib import Path

from ..contracts import AnalysisResult

FIXTURE = Path(__file__).resolve().parents[3] / "shared" / "fixtures" / "sample_result.json"


def analyze_mock(img_a, aligned_b, criteria: str) -> AnalysisResult:
    return AnalysisResult(**json.loads(FIXTURE.read_text(encoding="utf-8")))
