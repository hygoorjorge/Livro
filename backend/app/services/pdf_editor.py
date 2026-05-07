"""In-place PDF editing using PyMuPDF.

Strategy: redact the original span area then re-insert the new text in the
same bounding box using the same font/size/color. When the new text overflows,
the entire paragraph is re-flowed within the column derived from the spans'
bounding boxes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EditOp:
    page_num: int
    paragraph_index: int
    original_text: str
    final_text: str
    span_bboxes: list[tuple[float, float, float, float]]
    font_name: str
    font_size: float
    color: int


def _color_to_rgb(color: int) -> tuple[float, float, float]:
    r = ((color >> 16) & 0xFF) / 255.0
    g = ((color >> 8) & 0xFF) / 255.0
    b = (color & 0xFF) / 255.0
    return (r, g, b)


def _resolve_font(font_name: str) -> str:
    if not font_name:
        return "helv"
    name = font_name.lower()
    if "bold" in name and "italic" in name:
        return "tibo"
    if "bold" in name:
        return "tibo" if "times" in name or "roman" in name else "hebo"
    if "italic" in name or "oblique" in name:
        return "tiit" if "times" in name or "roman" in name else "heoi"
    if "times" in name or "roman" in name:
        return "tiro"
    if "courier" in name or "mono" in name:
        return "cour"
    return "helv"


def _column_bbox(bboxes: list[tuple[float, float, float, float]]) -> fitz.Rect:
    x0 = min(b[0] for b in bboxes)
    y0 = min(b[1] for b in bboxes)
    x1 = max(b[2] for b in bboxes)
    y1 = max(b[3] for b in bboxes)
    return fitz.Rect(x0, y0, x1, y1)


def apply_edits(
    source_pdf: str | Path,
    output_pdf: str | Path,
    edits: list[EditOp],
) -> dict:
    """Apply ``edits`` to ``source_pdf`` and write to ``output_pdf``.

    Returns a report with counts and any overflow warnings per edit.
    """
    doc = fitz.open(str(source_pdf))
    report = {"applied": 0, "overflow": 0, "warnings": []}
    try:
        edits_by_page: dict[int, list[EditOp]] = {}
        for e in edits:
            edits_by_page.setdefault(e.page_num, []).append(e)

        for page_num, page_edits in edits_by_page.items():
            page = doc[page_num - 1]
            for edit in page_edits:
                rect = _column_bbox(edit.span_bboxes)
                page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions()

            for edit in page_edits:
                rect = _column_bbox(edit.span_bboxes)
                fontname = _resolve_font(edit.font_name)
                color = _color_to_rgb(edit.color)

                inserted = page.insert_textbox(
                    rect,
                    edit.final_text,
                    fontsize=edit.font_size,
                    fontname=fontname,
                    color=color,
                    align=fitz.TEXT_ALIGN_JUSTIFY,
                )
                if inserted < 0:
                    expansion = fitz.Rect(
                        rect.x0,
                        rect.y0,
                        rect.x1,
                        rect.y1 + abs(inserted) + edit.font_size,
                    )
                    page.insert_textbox(
                        expansion,
                        edit.final_text,
                        fontsize=edit.font_size,
                        fontname=fontname,
                        color=color,
                        align=fitz.TEXT_ALIGN_JUSTIFY,
                    )
                    report["overflow"] += 1
                    report["warnings"].append(
                        {
                            "page": page_num,
                            "paragraph_index": edit.paragraph_index,
                            "extra_height": abs(inserted),
                        }
                    )
                report["applied"] += 1

        doc.save(str(output_pdf), garbage=4, deflate=True)
    finally:
        doc.close()
    return report


def replace_figure(
    source_pdf: str | Path,
    output_pdf: str | Path,
    page_num: int,
    bbox: tuple[float, float, float, float],
    replacement_image_path: str | Path,
) -> None:
    doc = fitz.open(str(source_pdf))
    try:
        page = doc[page_num - 1]
        rect = fitz.Rect(*bbox)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        page.insert_image(rect, filename=str(replacement_image_path))
        doc.save(str(output_pdf), garbage=4, deflate=True)
    finally:
        doc.close()
