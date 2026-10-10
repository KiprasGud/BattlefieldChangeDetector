"""PERSON 3: draw red boxes + labels on the image with optional sector grid."""
import unicodedata

import cv2
import numpy as np

from ..contracts import AnalysisResult

CATEGORY_CODES = {
    "missing_object": "MISS",
    "new_structure": "STRUCT",
    "terrain_change": "TERR",
    "unknown_anomaly": "UNK",
}

MAX_LABEL_CHARS = 32  # the AI label on a badge; longer ones end in "..."
BADGE_FONT, BADGE_SCALE, BADGE_THICKNESS = cv2.FONT_HERSHEY_DUPLEX, 0.55, 1


def badge_label(text: str, limit: int = MAX_LABEL_CHARS) -> str:
    """ASCII form of the AI label for cv2.putText, which cannot draw letters like "ė" or "š" (they become "e", "s")."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    ascii_text = " ".join(ascii_text.split())
    return ascii_text if len(ascii_text) <= limit else ascii_text[: limit - 3].rstrip() + "..."


def draw_grid_overlay(img: np.ndarray, opacity: float = 0.25) -> np.ndarray:
    """Draw a 4x4 tactical sector grid (columns A-D, rows 1-4) onto the image."""
    out = img.copy()
    overlay = img.copy()
    h, w = out.shape[:2]

    # Draw grid lines
    cols = ["A", "B", "C", "D"]
    rows = ["1", "2", "3", "4"]

    # 4 columns -> 3 interior lines, 4 rows -> 3 interior lines
    for i in range(1, 4):
        x = int(i * w / 4)
        y = int(i * h / 4)
        cv2.line(overlay, (x, 0), (x, h), (200, 200, 200), 1, cv2.LINE_AA)
        cv2.line(overlay, (0, y), (w, y), (200, 200, 200), 1, cv2.LINE_AA)

    # Blend grid lines with opacity
    cv2.addWeighted(overlay, opacity, out, 1 - opacity, 0, out)

    # Sector labels at the top-left of each cell
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.4, min(0.7, w / 1200))
    thickness = 1

    for col_idx, col_name in enumerate(cols):
        for row_idx, row_name in enumerate(rows):
            sector_name = f"{col_name}{row_name}"
            cell_x = int(col_idx * w / 4) + 8
            cell_y = int(row_idx * h / 4) + int(18 * font_scale / 0.5)

            # Subdued text label with slight dark shadow for legibility
            cv2.putText(out, sector_name, (cell_x + 1, cell_y + 1), font, font_scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
            cv2.putText(out, sector_name, (cell_x, cell_y), font, font_scale, (220, 220, 220), thickness, cv2.LINE_AA)

    return out


def annotate(img: np.ndarray, result: AnalysisResult, draw_grid: bool = False) -> np.ndarray:
    """Renders high-visibility tactical red boxes, numbered badges, and optional sector grid."""
    out = img.copy()
    h, w = out.shape[:2]

    if draw_grid:
        out = draw_grid_overlay(out)

    for i, c in enumerate(result.changes, 1):
        ymin, xmin, ymax, xmax = c.box
        # Normalize/clamp box coordinates to [0, 1000]
        ymin = max(0, min(1000, float(ymin)))
        ymax = max(0, min(1000, float(ymax)))
        xmin = max(0, min(1000, float(xmin)))
        xmax = max(0, min(1000, float(xmax)))

        if ymin > ymax:
            ymin, ymax = ymax, ymin
        if xmin > xmax:
            xmin, xmax = xmax, xmin

        px1 = int(xmin / 1000 * w)
        py1 = int(ymin / 1000 * h)
        px2 = int(xmax / 1000 * w)
        py2 = int(ymax / 1000 * h)

        # 1. Subtle dark drop-shadow border around the box for contrast
        cv2.rectangle(out, (max(0, px1 - 1), max(0, py1 - 1)), (min(w - 1, px2 + 1), min(h - 1, py2 + 1)), (0, 0, 0), 4, cv2.LINE_AA)
        # 2. Main tactical red bounding box (BGR: (0, 0, 230))
        cv2.rectangle(out, (px1, py1), (px2, py2), (20, 20, 240), 2, cv2.LINE_AA)

        # 3. Corner accent ticks to give a military HUD / tactical look: (corner x, corner y, inward x, inward y),
        #    top-left, top-right, bottom-left, bottom-right
        tick_len = max(6, min(18, int(min(px2 - px1, py2 - py1) * 0.25)))
        for x, y, dx, dy in ((px1, py1, 1, 1), (px2, py1, -1, 1), (px1, py2, 1, -1), (px2, py2, -1, -1)):
            cv2.line(out, (x, y), (x + dx * tick_len, y), (0, 255, 255), 2, cv2.LINE_AA)
            cv2.line(out, (x, y), (x, y + dy * tick_len), (0, 255, 255), 2, cv2.LINE_AA)

        # 4. Numbered label badge
        label_text = f"#{i}"
        if c.sector:
            label_text += f" [{c.sector}]"
        if c.category:
            label_text += f" {CATEGORY_CODES.get(c.category, 'UNK')}"
        name = badge_label(c.type)
        if name:
            label_text += f" - {name}"

        (txt_w, txt_h), _ = cv2.getTextSize(label_text, BADGE_FONT, BADGE_SCALE, BADGE_THICKNESS)

        # Badge positioning above box or inside box if too close to top; shifted left so the label stays in frame
        badge_y2 = py1 - 4 if py1 - (txt_h + 8) > 0 else py1 + txt_h + 10
        badge_y1 = badge_y2 - txt_h - 6
        badge_x1 = max(0, min(px1, w - 1 - (txt_w + 10)))
        badge_x2 = min(w - 1, badge_x1 + txt_w + 10)

        # Badge background: solid dark red/black with border
        cv2.rectangle(out, (badge_x1, badge_y1), (badge_x2, badge_y2), (20, 20, 20), -1)
        cv2.rectangle(out, (badge_x1, badge_y1), (badge_x2, badge_y2), (20, 20, 240), 1)

        # Text inside badge: white
        text_origin = (badge_x1 + 5, badge_y2 - 4)
        cv2.putText(out, label_text, text_origin, BADGE_FONT, BADGE_SCALE, (255, 255, 255), BADGE_THICKNESS, cv2.LINE_AA)

    return out
