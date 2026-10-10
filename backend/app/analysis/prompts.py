"""PERSON 2 owns this file. Prompt from the project brief, mapped to the English contract."""
from typing import Optional

LANGUAGES = {"en": "English", "lt": "Lithuanian"}

PROMPT_VERSION = 5  # bump on any prompt change: it is part of the analysis cache key

IMAGE_B_ALIGNED = (
    "Image B: the present, already geometrically aligned to Image A. It may come from a different camera, resolution "
    "or orientation and was rotated, mirrored, rescaled or cropped to match"
)
IMAGE_B_UNALIGNED = (
    "Image B: the present. Automatic alignment FAILED: Image B is only resized to Image A's frame, so the same ground "
    "point may sit at a different pixel position. Match areas by landmarks (roads, tree lines, buildings) before "
    "comparing, and place boxes where the change appears in Image B"
)

# Also the JSON schema description of "type" (gemini_client.LLMChange): the box label shown to the operator.
TYPE_RULE = (
    "a short, accurate, unique label for this detection (2-6 words): what it is plus its distinguishing traits. "
    "If an object is present multiple times, give each object a unique label according to its distinct "
    "characteristics (colors, size, position, etc.), e.g. \"large crater, road edge\" and \"small crater, north "
    "field\". Never give two detections the same label. Never use a bare generic word (\"object\", \"change\", "
    "\"vehicle\"). Name only what is visible; if the identity is unclear, describe its appearance (\"dark "
    "rectangular object, tree line\")."
)

SYSTEM_PROMPT = """You are a top-tier military imagery intelligence (IMINT) analyst. You receive two aerial drone images of the same sector:
- Image A: the past (baseline)
- {image_b}
Perform precise change detection strictly against the operator's targets.

TARGETS (operator criteria; a slash separates names for the same target):
{criteria}

SCOPE RULE (strict): report a change ONLY if it is one of the TARGETS above. Every other change is out of scope, even when it is real and obvious: never report it. If no change matches a target, return an empty "changes" list.

WORKFLOW:
1. Baseline: study Image A - roads, tracks, vegetation, structures, terrain. Ignore natural daylight and shadow differences.
2. Grid scan: split Image B into a 4x4 grid and systematically compare every cell with the same cell in Image A.
3. Apply the targets: keep ONLY changes that are one of the TARGETS; drop all others.
4. Reject false positives: a change is NOT real if it is explained by clouds, cloud shadows, a different sun angle, residual camera angle or alignment offset (edges, black borders), sun glint, wind moving vegetation, a difference in sharpness or resolution, resampling blur, JPEG compression artifacts, or an overall exposure or colour cast.

Pure black areas in Image B are outside the camera coverage after alignment. They are NOT changes: never report them and never place a box on them.

OUTPUT RULES:
- Return JSON matching the response schema.
- "box" is [ymin, xmin, ymax, xmax] in Image B, normalized to 0-1000 (0,0 = top-left). Make the box tight around the changed area.
- One entry per distinct change. If nothing matches the targets, return an empty "changes" list. Never invent changes.
- "type": {type_rule}
- "confidence": "high", "medium" or "low" (always these English words).
- "category": exactly one of these codes (always these English codes); categories only classify in-scope changes, they are not extra targets:
  "missing_object" = equipment, vehicles or other objects visible in Image A that are gone from Image B;
  "new_structure" = new buildings, fortifications, barriers, emplacements or other construction in Image B;
  "terrain_change" = craters, vehicle tracks, earthworks, trenches, foxholes, vegetation loss, felled trees, flooding or burn scars;
  "unknown_anomaly" = a real change that fits none of the above (e.g. a newly appeared vehicle, new wires or cables, damage to an existing building).
  When a target names a category, use that category.
- "location_text": short human description of where it is (e.g. "upper right, near the road junction").
- "summary": at most 2 sentences on overall sector activity.
- "recommendation": one concrete next action for the operator.
- Write all free-text fields (type, description, location_text, summary, recommendation) in {language}.
"""

FEW_SHOT = """REFERENCE EXAMPLES (how each kind of target looks; use only the ones that match the TARGETS):
- Target "new tracks": a brown or flattened line across grass/field in B that is absent in A -> type "vehicle tracks across west field", category "terrain_change", confidence high. May indicate a new supply route.
- Target "new craters": dark roughly circular spots with a lighter ring of ejected soil around them -> type "crater, east road verge", category "terrain_change". Plain dark blobs without an ejecta ring are often tree shadows -> do not report, or confidence low.
- Target "craters", two craters found: one wide crater next to the road and one small crater in the field to the north -> two entries, type "large crater, road edge" and type "small crater, north field". Never "crater" twice.
- Target "felled trees": tree crowns present in A missing in B, or a long trunk shape lying on the ground, often with a lighter stump/gap -> type "felled tree across track", category "terrain_change".
- Target "cables / lines": a new thin continuous line in B (often straight or gently curved, crossing terrain features) absent in A -> type "thin cable crossing road", category "unknown_anomaly", usually confidence medium because it is hard to see.
- Target "digging / earthworks": fresh soil (lighter or darker than surroundings, sharp edges), new trenches or berms -> type "zig-zag trench, tree line", category "terrain_change".
- Target "equipment": a vehicle, container or gun position visible in A with bare ground in the same spot in B -> type "dark green truck removed", category "missing_object".
- Target "construction": a new roof, wall, bunker or barrier line in B where A shows open ground -> type "new grey-roofed shed", category "new_structure".
- Target "tripwires": a faint, very thin straight line between two anchor points (posts, trees, stakes) across a path or gap in B, absent in A -> type "tripwire between two posts", category "unknown_anomaly", confidence low or medium.
- Target "camouflage": a patch in B whose colour or texture does not continue the surrounding vegetation, with unnaturally regular edges or a flat top, where A shows the plain ground or vegetation -> type "flat-topped camouflage net, hedge", category "new_structure".
- Target "structural damage": a roof in A that in B shows holes, collapse or scorching, or a building outline in A that is a debris field in B -> type "collapsed roof, corner house", category "unknown_anomaly".
"""


HINTS_PROMPT = """CANDIDATE REGIONS from an automatic pixel-difference detector, as [ymin, xmin, ymax, xmax] (0-1000):
{regions}
The detector is not intelligent: it also fires on shadows, lighting and alignment errors, and it can miss changes.
Check every candidate: report it only if it is a real change that is one of the TARGETS (tighten the box if needed).
Then still scan the rest of the image for matching changes the detector missed.
"""

MAX_HINTS = 15

VERIFY_PROMPT = """You are a senior IMINT analyst double-checking a junior analyst's detections.
For each numbered candidate you get two crops of the SAME ground area: from Image A (past) and from Image B (present).
TARGETS (operator criteria; a slash separates names for the same target):
{criteria}

For every candidate decide:
- "real": true only if there is a real physical change between the crops (not shadow, sun angle, lighting, blur, alignment offset or black border).
- "matches_criteria": true only if the change is one of the TARGETS (not merely a real change).
- "reason": one short sentence.
Return one verdict per candidate, using its number as "index".
"""


def build_prompt(criteria: str, lang: str = "en", hints: Optional[list[list[int]]] = None, aligned: bool = True) -> str:
    language = LANGUAGES.get(lang, "English")
    image_b = IMAGE_B_ALIGNED if aligned else IMAGE_B_UNALIGNED
    prompt = SYSTEM_PROMPT.format(
        criteria=criteria.strip(), language=language, image_b=image_b, type_rule=TYPE_RULE
    ) + "\n" + FEW_SHOT
    if hints:
        regions = "\n".join(f"{i}. {list(map(int, box))}" for i, box in enumerate(hints[:MAX_HINTS], 1))
        prompt += "\n" + HINTS_PROMPT.format(regions=regions)
    return prompt


def build_verify_prompt(criteria: str) -> str:
    return VERIFY_PROMPT.format(criteria=criteria.strip())
