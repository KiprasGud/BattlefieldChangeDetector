"""Runtime switches. The AI step and automatic batching can be toggled from the dashboard without a restart;
AI_ENABLED and AUTO_BATCH are the defaults."""
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


_auto_batch_override: Optional[bool] = None


def auto_batch_enabled() -> bool:
    """True: inbox files are batched as soon as they settle and queued batches run. False: files wait in the inbox
    unbatched and the worker pauses after the batch it is running."""
    if _auto_batch_override is not None:
        return _auto_batch_override
    return (os.getenv("AUTO_BATCH") or "1").strip().lower() in TRUE_VALUES


def set_auto_batch(value: Optional[bool]) -> None:
    """Override AUTO_BATCH until restart; None goes back to the environment value."""
    global _auto_batch_override
    _auto_batch_override = value
