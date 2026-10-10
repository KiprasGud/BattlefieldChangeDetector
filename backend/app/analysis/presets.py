"""Pre-made target classes. A selected class reaches the AI model as its label, plain text joined with the
operator's free-text query: exactly the same pathway as a typed query."""
from typing import NamedTuple


class Preset(NamedTuple):
    label: str
    shortcut: str
    tags: tuple[str, ...]  # offline mock fixture tags (analysis/mock.py)


PRESETS: dict[str, Preset] = {
    "wires": Preset("New Wires / Tripwires / Comms Lines", "Alt+1", ("cable",)),
    "craters": Preset("Craters / Artillery Impacts", "Alt+2", ("crater",)),
    "trenches": Preset("Trenches / Foxholes / Earthworks", "Alt+3", ("earthworks",)),
    "tracks": Preset("Vehicle Tracks / Heavy Equipment", "Alt+4", ("tracks",)),
    "camouflage": Preset("Camouflage Netting / Concealed Positions", "Alt+5", ("camouflage",)),
    "damage": Preset("Structural Damage / Rubble", "Alt+6", ("structure",)),
    "vehicles": Preset("Vehicles / Equipment", "Alt+7", ("vehicle",)),
    "felled_trees": Preset("Felled Trees / Clearing", "Alt+8", ("tree",)),
}


def catalog() -> list[dict[str, str]]:
    return [{"id": pid, "label": p.label, "shortcut": p.shortcut} for pid, p in PRESETS.items()]


def parse_ids(raw: str) -> list[str]:
    """Comma-separated preset ids, deduplicated in order; ValueError on an unknown id."""
    ids = list(dict.fromkeys(s.strip() for s in raw.split(",") if s.strip()))
    unknown = [i for i in ids if i not in PRESETS]
    if unknown:
        raise ValueError(f"Unknown target class: {', '.join(unknown)}")
    return ids


def build_criteria(preset_ids: list[str], custom: str = "") -> str:
    """Criteria text for the AI prompt: preset labels and the custom text, comma-joined. Custom text alone passes
    through unchanged."""
    custom = custom.strip()
    return ", ".join([PRESETS[i].label for i in preset_ids] + ([custom] if custom else []))


def split_criteria(text: str) -> tuple[list[str], str]:
    """Inverse of build_criteria: (preset ids, custom text). Parts that are not a preset label are custom."""
    by_label = {p.label.lower(): pid for pid, p in PRESETS.items()}
    ids, rest = [], []
    for part in (s.strip() for s in text.split(",")):
        if part.lower() in by_label:
            ids.append(by_label[part.lower()])
        elif part:
            rest.append(part)
    return ids, ", ".join(rest)
