"""Pre-made target classes. Each one is a written instruction for the AI model (the same pathway as the
operator's free-text query), never a template or pixel rule: the model does all visual generalization."""
from typing import NamedTuple


class Preset(NamedTuple):
    label: str
    shortcut: str
    instruction: str
    tags: tuple[str, ...]  # offline mock fixture tags (analysis/mock.py)


PRESETS: dict[str, Preset] = {
    "wires": Preset(
        "New Wires / Tripwires / Comms Lines", "Alt+1",
        "new thin continuous lines in Image B absent in Image A: field telephone or comms cables, tripwires, power "
        "lines, fibre-optic lines from drones. They are often only a few pixels wide, straight or gently curved, "
        "crossing grass, roads or ditches; follow faint lines end to end. Category \"unknown_anomaly\".",
        ("cable",),
    ),
    "craters": Preset(
        "Craters / Artillery Impacts", "Alt+2",
        "new impact craters of any size: roughly circular depressions, usually a darker centre with a lighter ring "
        "or spray of ejected soil, sometimes water-filled or scorched, in fields, roads or next to buildings. Detect "
        "them regardless of lighting, scale, viewing angle or clustering. Category \"terrain_change\".",
        ("crater",),
    ),
    "trenches": Preset(
        "Trenches / Foxholes / Earthworks", "Alt+3",
        "new excavation: trench lines (often zig-zag), foxholes and fighting positions, dugouts, berms, anti-tank "
        "ditches, fresh spoil heaps. Look for freshly turned soil with sharp edges, lighter or darker than the "
        "surroundings. Category \"terrain_change\" (\"new_structure\" for revetted or covered positions).",
        ("earthworks",),
    ),
    "tracks": Preset(
        "Vehicle Tracks / Heavy Equipment", "Alt+4",
        "new vehicle tracks and heavy-equipment movement: parallel ruts, flattened or churned vegetation, new "
        "dirt paths, turning circles, tracked-vehicle marks across fields or verges. Category \"terrain_change\".",
        ("tracks",),
    ),
    "camouflage": Preset(
        "Camouflage Netting / Concealed Positions", "Alt+5",
        "camouflage netting and concealed positions: patches whose texture or colour does not match the "
        "surroundings, unnaturally regular outlines or flat-topped shapes over vegetation, cut branches piled over "
        "objects, new shadows from covered equipment. Category \"new_structure\".",
        ("camouflage",),
    ),
    "damage": Preset(
        "Structural Damage / Rubble", "Alt+6",
        "damage to existing buildings and infrastructure: collapsed or holed roofs, missing walls, rubble and "
        "debris fields, burn marks, destroyed bridges or vehicles. Category \"unknown_anomaly\".",
        ("structure",),
    ),
    "vehicles": Preset(
        "Vehicles / Equipment", "Alt+7",
        "vehicles, artillery pieces, containers or other equipment that appeared in Image B (category "
        "\"unknown_anomaly\") or that were present in Image A and are gone in Image B (category \"missing_object\").",
        ("vehicle",),
    ),
    "felled_trees": Preset(
        "Felled Trees / Clearing", "Alt+8",
        "felled trees and cleared vegetation: tree crowns present in Image A missing in Image B, trunks lying on the "
        "ground, new gaps in tree lines, cleared fields of fire, abatis. Category \"terrain_change\".",
        ("tree",),
    ),
}

HEADER = "DETECT THESE TARGET CLASSES:"
CUSTOM = "OPERATOR CUSTOM QUERY:"


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
    """Criteria text for the AI prompt. Custom text alone passes through unchanged."""
    custom = custom.strip()
    if not preset_ids:
        return custom
    lines = [HEADER] + [f"- {PRESETS[i].label.upper()}: {PRESETS[i].instruction}" for i in preset_ids]
    if custom:
        lines.append(f"{CUSTOM} {custom}")
    return "\n".join(lines)


def split_criteria(text: str) -> tuple[list[str], str]:
    """Inverse of build_criteria: (preset ids, custom text). Plain text is all custom."""
    if not text.startswith(HEADER):
        return [], text
    body, _, custom = text.partition(f"\n{CUSTOM}")
    by_label = {p.label.upper(): pid for pid, p in PRESETS.items()}
    ids = [pid for line in body.splitlines()[1:]
           if line.startswith("- ") and (pid := by_label.get(line[2:].split(":", 1)[0]))]
    return ids, custom.strip()
