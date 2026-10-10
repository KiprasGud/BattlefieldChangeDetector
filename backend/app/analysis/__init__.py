import os

from .gemini_client import analyze_with_gemini
from .mock import analyze_mock


def analyze(img_a, aligned_b, criteria: str, lang: str = "en"):
    """PERSON 2 owns this package. Returns AnalysisResult. MOCK_LLM=1 (or no key) -> fixture."""
    if os.getenv("MOCK_LLM", "1") == "1" or not os.getenv("GEMINI_API_KEY"):
        return analyze_mock(img_a, aligned_b, criteria)
    return analyze_with_gemini(img_a, aligned_b, criteria, lang)


__all__ = ["analyze"]
