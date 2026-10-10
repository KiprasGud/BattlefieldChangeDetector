"""Final report of a reviewed batch: accepted findings only, as JSON, as one self-contained HTML page (images
embedded), or as a PDF (side-by-side boxed frames, findings grouped by category)."""
import base64
import html
import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from fpdf import FPDF

from ..analysis.gemini_client import crop_box
from ..contracts import CATEGORY_LABELS, AnalysisResult, Change
from .annotate import annotate

FULL_SIDE = 1280
CROP_SIDE = 220


def _clock(t: Optional[float]) -> str:
    t = t or 0.0
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def verified_pairs(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Pairs that keep at least one accepted finding, each with only its accepted findings."""
    out = []
    for pair in detail.get("pairs", []):
        accepted = [f for f in pair["findings"] if f["review_status"] == "accepted"]
        if accepted:
            out.append({**pair, "findings": accepted})
    return out


def leg_label(item: dict[str, Any]) -> str:
    """'Day1→Day2' for a leg or for a pair carrying its leg's tags."""
    return f"{item.get('tag_a') or '?'}→{item.get('tag_b') or '?'}"


def _totals(pairs: list[dict[str, Any]]) -> dict[str, int]:
    totals = {label: 0 for label in CATEGORY_LABELS.values()}
    for pair in pairs:
        for f in pair["findings"]:
            totals[CATEGORY_LABELS.get(f["category"], CATEGORY_LABELS["unknown_anomaly"])] += 1
    return totals


def targets(detail: dict[str, Any]) -> str:
    """What the batch was searched for: its criteria when the AI ran, else every heatmap region."""
    if not detail.get("ai_enabled"):
        return "All changes (CV only)"
    return detail.get("criteria") or "All changes"


def build_json(detail: dict[str, Any]) -> dict[str, Any]:
    pairs = verified_pairs(detail)
    return {
        "report": "verified changes",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "batch": {k: detail.get(k) for k in (
            "id", "site", "name_a", "name_b", "tag_a", "tag_b", "kind_a", "kind_b", "ai_enabled", "created_at")},
        "targets": targets(detail),
        "legs": [
            {"leg": leg["idx"], "label": leg_label(leg), **{k: leg.get(k) for k in (
                "tag_a", "tag_b", "name_a", "name_b", "kind_a", "kind_b", "status")}}
            for leg in detail.get("legs", [])
        ],
        "totals": _totals(pairs),
        "verified_changes": [
            {
                "leg": p.get("leg_idx"), "leg_label": leg_label(p), "pair": p["idx"], "time_a": p["time_a"], "time_b": p["time_b"], "source": p["source"],
                "category": f["category"], "category_label": CATEGORY_LABELS.get(f["category"], f["category"]),
                "type": f["type"], "description": f["description"], "location_text": f["location_text"],
                "confidence": f["confidence"], "sector": f["sector"], "box": f["box"],
                "reviewed_at": f["reviewed_at"],
            }
            for p in pairs for f in p["findings"]
        ],
    }


def _read(path: Path) -> Optional[np.ndarray]:
    if not path.is_file():
        return None
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def _jpeg(img: Optional[np.ndarray], side: int) -> Optional[bytes]:
    """JPEG bytes of img scaled down to fit side x side; None when there is no image."""
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    if max(h, w) > side:
        s = side / max(h, w)
        img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


def _data_uri(img: Optional[np.ndarray], side: int) -> str:
    data = _jpeg(img, side)
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii") if data else ""


def _img(uri: str, alt: str, cls: str = "") -> str:
    return f'<img class="{cls}" src="{uri}" alt="{html.escape(alt)}">' if uri else '<div class="missing">[IMAGE UNAVAILABLE]</div>'


def _changes(findings: list[dict[str, Any]]) -> list[Change]:
    return [Change(type=f["type"], description=f["description"], location_text=f["location_text"],
                   confidence=f["confidence"], box=f["box"], sector=f["sector"], category=f["category"])
            for f in findings]


def _boxed(img: Optional[np.ndarray], changes: list[Change]) -> Optional[np.ndarray]:
    if img is None:
        return None
    return annotate(img, AnalysisResult(report_date="", summary="", changes=changes, recommendation=""))


def build_html(detail: dict[str, Any], batch_dir: Path) -> str:
    e = html.escape
    pairs = verified_pairs(detail)
    totals = _totals(pairs)
    sections = []
    for p in pairs:
        pair_dir = Path(batch_dir) / f"pair_{p['idx']:02d}"
        img_a, img_b = _read(pair_dir / "a.jpg"), _read(pair_dir / "aligned_b.jpg")
        changes = _changes(p["findings"])
        annotated = _boxed(img_b, changes)
        rows = []
        for i, (f, c) in enumerate(zip(p["findings"], changes), 1):
            crop_a = _data_uri(crop_box(img_a, c.box), CROP_SIDE) if img_a is not None else ""
            crop_b = _data_uri(crop_box(img_b, c.box), CROP_SIDE) if img_b is not None else ""
            rows.append(
                f"<tr><td class='mono'>#{i}</td><td>{e(CATEGORY_LABELS.get(f['category'], f['category']))}</td>"
                f"<td>{e(f['type'])}</td><td class='mono'>{e(f['confidence'].upper())}</td>"
                f"<td class='mono'>{e(f['sector'] or '-')}</td><td>{e(f['description'])}</td>"
                f"<td>{_img(crop_a, 'before', 'crop')}</td><td>{_img(crop_b, 'after', 'crop')}</td></tr>"
            )
        sections.append(
            f"<section class='pair'><h2>{e(leg_label(p).upper())} &middot; PAIR {p['idx']:02d} &middot; "
            f"A@{_clock(p['time_a'])} &harr; "
            f"B@{_clock(p['time_b'])}</h2>"
            f"<div class='meta mono'>INLIERS {p['inliers']} &middot; OVERLAP {p['overlap'] * 100:.0f}% &middot; "
            f"SSIM {p['ssim']:.2f} &middot; SOURCE {e(str(p['source']).upper())}</div>"
            f"{_img(_data_uri(annotated, FULL_SIDE), 'annotated frame', 'full')}"
            "<table><tr><th>#</th><th>Category</th><th>Type</th><th>Conf.</th><th>Sector</th><th>Description</th>"
            f"<th>Before</th><th>After</th></tr>{''.join(rows)}</table></section>"
        )
    total_rows = "".join(f"<tr><td>{e(label)}</td><td class='mono'>{n}</td></tr>" for label, n in totals.items())
    body = "".join(sections) or "<p class='empty'>No verified changes: accept findings in the review dashboard first.</p>"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verified changes - {e(str(detail.get('site') or ''))}</title>
<style>
  body {{ margin: 0; padding: 24px; background: #fff; color: #000; font: 13px/1.4 Inter, Arial, sans-serif; }}
  h1 {{ font-size: 18px; letter-spacing: .08em; margin: 0 0 8px; }}
  h2 {{ font-size: 14px; margin: 0 0 4px; }}
  .mono, td.mono, .meta {{ font-family: "JetBrains Mono", "Fira Code", monospace; }}
  .meta {{ font-size: 11px; color: #374151; margin-bottom: 8px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0 0; }}
  th, td {{ border: 1px solid #9CA3AF; padding: 4px 6px; text-align: left; vertical-align: top; }}
  th {{ background: #E5E7EB; font-size: 11px; text-transform: uppercase; }}
  .head td {{ border: none; padding: 0 16px 0 0; }}
  .pair {{ border: 1px solid #374151; padding: 12px; margin: 16px 0; break-inside: avoid; }}
  img.full {{ max-width: 100%; display: block; border: 1px solid #9CA3AF; }}
  img.crop {{ max-width: 220px; display: block; }}
  .missing, .empty {{ color: #6B7280; font-family: monospace; }}
  * {{ border-radius: 0; box-shadow: none; }}
</style></head><body>
<h1>VERIFIED CHANGE REPORT</h1>
<table class="head mono"><tr>
  <td>SITE: {e(str(detail.get('site') or '-'))}</td>
  <td>LEGS: {e(', '.join(leg_label(leg) for leg in detail.get('legs', [])) or '-')}</td>
  <td>A: {e(str(detail.get('name_a') or '-'))} ({e(str(detail.get('kind_a') or '?'))})</td>
  <td>B: {e(str(detail.get('name_b') or '-'))} ({e(str(detail.get('kind_b') or '?'))})</td>
  <td>AI: {'ON' if detail.get('ai_enabled') else 'OFF'}</td>
  <td>TARGETS: {e(targets(detail))}</td>
  <td>GENERATED: {generated}</td>
</tr></table>
<table style="max-width: 420px"><tr><th>Category</th><th>Verified</th></tr>{total_rows}</table>
{body}
</body></html>
"""


# --- PDF -------------------------------------------------------------------------------------------------------------

_WIN_FONTS = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
_FONTS = [  # (regular, bold): the first pair on disk is embedded, so names with non-Latin-1 letters print
    (_WIN_FONTS / "arial.ttf", _WIN_FONTS / "arialbd.ttf"),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    (Path("/Library/Fonts/Arial.ttf"), Path("/Library/Fonts/Arial Bold.ttf")),
]
MARGIN = 12      # mm, A4 portrait
LINE = 4.5       # mm per text line
CROP_MM = 26     # before/after crop cell
FRAME_MAX_MM = 110


class _Pdf(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, MARGIN)
        self.family, self.unicode = "helvetica", False
        for regular, bold in _FONTS:
            if regular.is_file() and bold.is_file():
                self.add_font("body", "", str(regular))
                self.add_font("body", "B", str(bold))
                self.family, self.unicode = "body", True
                break

    @property
    def width(self) -> float:
        return self.w - 2 * MARGIN

    def text_(self, s: Any) -> str:
        s = str(s).replace("\u2192", "->").replace("\u2194", "<->")
        return s if self.unicode else s.encode("latin-1", "replace").decode("latin-1")

    def font(self, size: float, bold: bool = False) -> None:
        self.set_font(self.family, "B" if bold else "", size)

    def need(self, height: float) -> None:
        """Start a new page unless height mm still fit on this one."""
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def footer(self) -> None:
        self.set_y(-MARGIN + 2)
        self.font(7)
        self.set_text_color(107, 114, 128)
        self.cell(0, 4, f"VERIFIED CHANGE REPORT  -  page {self.page_no()}/{{nb}}", align="R")
        self.set_text_color(0, 0, 0)

    def picture(self, img: Optional[np.ndarray], side: int, x: float, y: float, w: float, h: float) -> None:
        """img fitted into the w x h mm cell at (x, y); a placeholder when it is missing."""
        data = _jpeg(img, side)
        if data is None:
            self.set_xy(x, y)
            self.font(7)
            self.set_text_color(107, 114, 128)
            self.cell(w, h, "[IMAGE UNAVAILABLE]", border=1, align="C")
            self.set_text_color(0, 0, 0)
            return
        ih, iw = img.shape[:2]
        s = min(w / iw, h / ih)
        self.image(BytesIO(data), x=x + (w - iw * s) / 2, y=y + (h - ih * s) / 2, w=iw * s, h=ih * s)

    def lines(self, text: str, w: float) -> int:
        return len(self.multi_cell(w, LINE, self.text_(text), dry_run=True, output="LINES")) or 1


def _pdf_header(pdf: _Pdf, detail: dict[str, Any], totals: dict[str, int]) -> None:
    pdf.font(16, bold=True)
    pdf.cell(0, 9, "VERIFIED CHANGE REPORT", new_x="LMARGIN", new_y="NEXT")
    meta = [
        ("Site", detail.get("site") or "-"),
        ("Legs", ", ".join(leg_label(leg) for leg in detail.get("legs", [])) or "-"),
        ("A", f"{detail.get('name_a') or '-'} ({detail.get('kind_a') or '?'})"),
        ("B", f"{detail.get('name_b') or '-'} ({detail.get('kind_b') or '?'})"),
        ("AI", "ON" if detail.get("ai_enabled") else "OFF"),
        ("Targets", targets(detail)),
        ("Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    for key, value in meta:
        pdf.font(8, bold=True)
        pdf.cell(22, LINE, key.upper())
        pdf.font(8)
        pdf.multi_cell(0, LINE, pdf.text_(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_fill_color(229, 231, 235)
    pdf.font(8, bold=True)
    pdf.cell(70, 6, "CATEGORY", border=1, fill=True)
    pdf.cell(22, 6, "VERIFIED", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.font(8)
    for label, n in totals.items():
        pdf.cell(70, 6, pdf.text_(label), border=1)
        pdf.cell(22, 6, str(n), border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _pdf_pair(pdf: _Pdf, p: dict[str, Any], batch_dir: Path) -> None:
    """One verified pair: title, A and aligned B side by side with the boxes, then its findings by category."""
    pair_dir = Path(batch_dir) / f"pair_{p['idx']:02d}"
    img_a, img_b = _read(pair_dir / "a.jpg"), _read(pair_dir / "aligned_b.jpg")
    changes = _changes(p["findings"])
    gap = 4
    col = (pdf.width - gap) / 2
    ref = img_a if img_a is not None else img_b
    img_h = min(col * ref.shape[0] / ref.shape[1] if ref is not None else col * 0.75, FRAME_MAX_MM)

    pdf.need(6 + 5 + 5 + img_h + 4)  # title, meta, captions and frames stay on one page
    pdf.set_draw_color(55, 65, 81)
    pdf.line(MARGIN, pdf.get_y(), MARGIN + pdf.width, pdf.get_y())
    pdf.ln(2)
    pdf.font(11, bold=True)
    pdf.cell(0, 6, pdf.text_(f"{leg_label(p).upper()}  -  PAIR {p['idx']:02d}  -  "
                             f"A@{_clock(p['time_a'])} <-> B@{_clock(p['time_b'])}"), new_x="LMARGIN", new_y="NEXT")
    pdf.font(7)
    pdf.set_text_color(55, 65, 81)
    pdf.cell(0, 5, pdf.text_(f"INLIERS {p['inliers']}  -  OVERLAP {(p['overlap'] or 0) * 100:.0f}%  -  "
                             f"SSIM {(p['ssim'] or 0):.2f}  -  SOURCE {str(p['source']).upper()}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.font(7, bold=True)
    pdf.cell(col + gap, 5, pdf.text_(f"BEFORE (A, {p.get('tag_a') or '?'})"))
    pdf.cell(col, 5, pdf.text_(f"AFTER (B ALIGNED, {p.get('tag_b') or '?'})"), new_x="LMARGIN", new_y="NEXT")
    y = pdf.get_y()
    pdf.picture(_boxed(img_a, changes), FULL_SIDE, MARGIN, y, col, img_h)
    pdf.picture(_boxed(img_b, changes), FULL_SIDE, MARGIN + col + gap, y, col, img_h)
    pdf.set_xy(MARGIN, y + img_h + 3)

    by_category: dict[str, list[tuple[int, dict[str, Any], Change]]] = {}
    for i, (f, c) in enumerate(zip(p["findings"], changes), 1):  # numbered as the badges on the frames
        label = CATEGORY_LABELS.get(f["category"], CATEGORY_LABELS["unknown_anomaly"])
        by_category.setdefault(label, []).append((i, f, c))
    meta_w = 44
    desc_w = pdf.width - meta_w - 2 * CROP_MM - 4
    for label in CATEGORY_LABELS.values():
        rows = by_category.get(label)
        if not rows:
            continue
        pdf.need(7 + CROP_MM + 2)
        pdf.set_fill_color(229, 231, 235)
        pdf.font(8, bold=True)
        pdf.cell(0, 6, pdf.text_(f"{label.upper()}  ({len(rows)})"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        for i, f, c in rows:
            meta = f"#{i}  {f['type']}\nCONF. {str(f['confidence']).upper()}\nSECTOR {f['sector'] or '-'}"
            desc = f["description"] + (f"\nLocation: {f['location_text']}" if f.get("location_text") else "")
            pdf.font(8)
            row_h = max(CROP_MM, LINE * max(pdf.lines(meta, meta_w), pdf.lines(desc, desc_w))) + 2
            pdf.need(row_h)
            y = pdf.get_y()
            pdf.set_xy(MARGIN, y)
            pdf.multi_cell(meta_w, LINE, pdf.text_(meta))
            pdf.set_xy(MARGIN + meta_w, y)
            pdf.multi_cell(desc_w, LINE, pdf.text_(desc))
            x = MARGIN + meta_w + desc_w + 2
            pdf.picture(crop_box(img_a, c.box) if img_a is not None else None, CROP_SIDE, x, y, CROP_MM, CROP_MM)
            pdf.picture(crop_box(img_b, c.box) if img_b is not None else None, CROP_SIDE, x + CROP_MM + 2, y,
                        CROP_MM, CROP_MM)
            pdf.set_draw_color(209, 213, 219)
            pdf.line(MARGIN, y + row_h - 1, MARGIN + pdf.width, y + row_h - 1)
            pdf.set_xy(MARGIN, y + row_h)
    pdf.ln(4)


def build_pdf(detail: dict[str, Any], batch_dir: Path) -> bytes:
    pairs = verified_pairs(detail)
    pdf = _Pdf()
    pdf.set_title(pdf.text_(f"Verified changes - {detail.get('site') or ''}"))
    pdf.alias_nb_pages()
    pdf.add_page()
    _pdf_header(pdf, detail, _totals(pairs))
    if not pairs:
        pdf.font(9)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(0, 6, "No verified changes: accept findings in the review dashboard first.")
    for p in pairs:
        _pdf_pair(pdf, p, batch_dir)
    return bytes(pdf.output())
