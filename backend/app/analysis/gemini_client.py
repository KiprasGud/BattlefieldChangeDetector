"""PERSON 2: call Gemini with both images + prompt, JSON-schema output, retries, validate."""
from ..contracts import AnalysisResult


def analyze_with_gemini(img_a, aligned_b, criteria: str, lang: str = "en") -> AnalysisResult:
    # TODO(P2): encode images (cv2.imencode), build prompt via prompts.build_prompt(criteria, lang),
    # call google-genai with response_schema=AnalysisResult, validate, drop bad boxes, add sectors.
    raise NotImplementedError("P2: implement Gemini call")
