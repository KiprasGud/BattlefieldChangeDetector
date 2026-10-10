"""Runtime switches. The AI step can be toggled from the dashboard without a restart; AI_ENABLED is the default."""
import os
from typing import Optional

TRUE_VALUES = {"1", "true", "yes", "on"}

_ai_override: Optional[bool] = None


def ai_enabled() -> bool:
    """True: Gemini analyzes matched pairs (deep analysis). False: the pipeline stops after the CV diff."""
    if _ai_override is not None:
        return _ai_override
    return (os.getenv("AI_ENABLED") or "1").strip().lower() in TRUE_VALUES


def set_ai_enabled(value: Optional[bool]) -> None:
    """Override AI_ENABLED until restart; None goes back to the environment value."""
    global _ai_override
    _ai_override = value
