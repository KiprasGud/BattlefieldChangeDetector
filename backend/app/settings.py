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


_batch_target: tuple[list[str], str] = ([], "")


def batch_target() -> tuple[list[str], str]:
    """What batches queued from now on tell the AI to look for: (preset ids, free-text query). Both empty: the
    default "any real change" criteria (batch.batch_criteria)."""
    return list(_batch_target[0]), _batch_target[1]


def set_batch_target(preset_ids: list[str], query: str) -> None:
    """Set the batch target until restart; ids must already be validated (presets.parse_ids)."""
    global _batch_target
    _batch_target = (list(preset_ids), query.strip())
