"""Final report of a reviewed batch: accepted findings only, as JSON or as one self-contained HTML page
(images embedded, printable to PDF from the browser)."""
import base64
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

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


def build_json(detail: dict[str, Any]) -> dict[str, Any]:
    pairs = verified_pairs(detail)
    return {
        "report": "verified changes",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "batch": {k: detail.get(k) for k in (
            "id", "site", "name_a", "name_b", "tag_a", "tag_b", "kind_a", "kind_b", "ai_enabled", "created_at")},
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


def _data_uri(img: Optional[np.ndarray], side: int) -> str:
    if img is None or img.size == 0:
        return ""
    h, w = img.shape[:2]
    if max(h, w) > side:
        s = side / max(h, w)
        img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def _img(uri: str, alt: str, cls: str = "") -> str:
    return f'<img class="{cls}" src="{uri}" alt="{html.escape(alt)}">' if uri else '<div class="missing">[IMAGE UNAVAILABLE]</div>'


def build_html(detail: dict[str, Any], batch_dir: Path) -> str:
    e = html.escape
    pairs = verified_pairs(detail)
    totals = _totals(pairs)
    sections = []
    for p in pairs:
        pair_dir = Path(batch_dir) / f"pair_{p['idx']:02d}"
        img_a, img_b = _read(pair_dir / "a.jpg"), _read(pair_dir / "aligned_b.jpg")
        changes = [Change(type=f["type"], description=f["description"], location_text=f["location_text"],
                          confidence=f["confidence"], box=f["box"], sector=f["sector"], category=f["category"])
                   for f in p["findings"]]
        annotated = None
        if img_b is not None:
            annotated = annotate(img_b, AnalysisResult(report_date="", summary="", changes=changes, recommendation=""))
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
  <td>GENERATED: {generated}</td>
</tr></table>
<table style="max-width: 420px"><tr><th>Category</th><th>Verified</th></tr>{total_rows}</table>
{body}
</body></html>
"""
