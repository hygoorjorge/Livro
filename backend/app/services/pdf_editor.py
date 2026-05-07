"""In-place PDF editing using PyMuPDF.

Strategy: redact each edited paragraph then re-insert the new text in the
same bounding box using the same font/size/color. When the new text
overflows the original column height, the paragraph's box is grown downward
and every subsequent paragraph on the same page is shifted by the same
amount (cross-paragraph reflow). Page-spilling content is left for manual
review — we do not move text across pages automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class PageParagraph:
    """Original paragraph layout used to recompute reflow when an edit grows."""

    paragraph_index: int
    text: str
    span_bboxes: list[tuple[float, float, float, float]]
    font_name: str
    font_size: float
    color: int


@dataclass
class _ResolvedEdit:
    op: EditOp | None
    layout: PageParagraph

    @property
    def text(self) -> str:
        return self.op.final_text if self.op is not None else self.layout.text

    @property
    def font_size(self) -> float:
        return self.op.font_size if self.op is not None else self.layout.font_size

    @property
    def font_name(self) -> str:
        return self.op.font_name if self.op is not None else self.layout.font_name

    @property
    def color(self) -> int:
        return self.op.color if self.op is not None else self.layout.color


def _color_to_rgb(color: int) -> tuple[float, float, float]:
    r = ((color >> 16) & 0xFF) / 255.0
    g = ((color >> 8) & 0xFF) / 255.0
    b = (color & 0xFF) / 255.0
    return (r, g, b)


def _resolve_font(font_name: str) -> str:
    if not font_name:
        return "helv"
    name = font_name.lower()
    if "bold" in name and ("italic" in name or "oblique" in name):
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


def _try_insert(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontsize: float,
    fontname: str,
    color: tuple[float, float, float],
) -> float:
    """Returns extra height needed (0 if it fit)."""
    inserted = page.insert_textbox(
        rect,
        text,
        fontsize=fontsize,
        fontname=fontname,
        color=color,
        align=fitz.TEXT_ALIGN_JUSTIFY,
    )
    if inserted >= 0:
        return 0.0
    return abs(inserted) + fontsize


def apply_edits(
    source_pdf: str | Path,
    output_pdf: str | Path,
    edits: list[EditOp],
    page_layouts: dict[int, list[PageParagraph]] | None = None,
) -> dict:
    """Apply ``edits`` to ``source_pdf`` and write to ``output_pdf``.

    ``page_layouts`` is the original paragraph layout per page (1-indexed). When
    provided, the editor recomputes a per-page reflow: an overflowing edit
    pushes subsequent paragraphs on the same page downward instead of just
    expanding the local box. When omitted, falls back to local box expansion.
    """
    doc = fitz.open(str(source_pdf))
    report = {"applied": 0, "overflow": 0, "page_overflow": 0, "warnings": []}
    edits_by_page: dict[int, dict[int, EditOp]] = {}
    for e in edits:
        edits_by_page.setdefault(e.page_num, {})[e.paragraph_index] = e

    try:
        for page_num, indexed_edits in edits_by_page.items():
            page = doc[page_num - 1]
            layouts = (page_layouts or {}).get(page_num)

            if layouts is None:
                _apply_page_local(page, list(indexed_edits.values()), report)
                continue

            ordered = sorted(layouts, key=lambda p: p.paragraph_index)
            resolved: list[_ResolvedEdit] = [
                _ResolvedEdit(op=indexed_edits.get(layout.paragraph_index), layout=layout)
                for layout in ordered
            ]
            if not any(item.op for item in resolved):
                continue
            _apply_page_with_reflow(page, resolved, report, page_num)

        doc.save(str(output_pdf), garbage=4, deflate=True)
    finally:
        doc.close()
    return report


def _apply_page_local(
    page: fitz.Page, page_edits: list[EditOp], report: dict
) -> None:
    """Fallback path: edit-by-edit redact + reinsert with local box growth."""
    for edit in page_edits:
        rect = _column_bbox(edit.span_bboxes)
        page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()
    for edit in page_edits:
        rect = _column_bbox(edit.span_bboxes)
        fontname = _resolve_font(edit.font_name)
        color = _color_to_rgb(edit.color)
        extra = _try_insert(page, rect, edit.final_text, edit.font_size, fontname, color)
        if extra > 0:
            grown = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + extra)
            page.insert_textbox(
                grown,
                edit.final_text,
                fontsize=edit.font_size,
                fontname=fontname,
                color=color,
                align=fitz.TEXT_ALIGN_JUSTIFY,
            )
            report["overflow"] += 1
            report["warnings"].append(
                {"page": page.number + 1, "extra_height": extra}
            )
        report["applied"] += 1


def _apply_page_with_reflow(
    page: fitz.Page,
    items: list[_ResolvedEdit],
    report: dict,
    page_num: int,
) -> None:
    page_height = page.rect.height
    current_offset = 0.0
    new_bboxes: list[fitz.Rect] = []

    for item in items:
        original = _column_bbox(item.layout.span_bboxes)
        shifted = fitz.Rect(
            original.x0,
            original.y0 + current_offset,
            original.x1,
            original.y1 + current_offset,
        )
        height = shifted.height
        fontname = _resolve_font(item.font_name)
        color = _color_to_rgb(item.color)

        probe_rect = fitz.Rect(shifted.x0, shifted.y0, shifted.x1, shifted.y0 + height)
        extra = _measure_overflow(
            page, probe_rect, item.text, item.font_size, fontname, color
        )
        if extra > 0:
            current_offset += extra
            shifted = fitz.Rect(
                shifted.x0, shifted.y0, shifted.x1, shifted.y1 + extra
            )
            if item.op is not None:
                report["overflow"] += 1
        new_bboxes.append(shifted)

        if shifted.y1 > page_height:
            report["page_overflow"] += 1
            report["warnings"].append(
                {
                    "page": page_num,
                    "paragraph_index": item.layout.paragraph_index,
                    "reason": "spilled past page bottom (manual review needed)",
                }
            )

    for item, layout_rect in zip(items, new_bboxes):
        original = _column_bbox(item.layout.span_bboxes)
        page.add_redact_annot(original, fill=(1, 1, 1))
    page.apply_redactions()

    for item, target_rect in zip(items, new_bboxes):
        fontname = _resolve_font(item.font_name)
        color = _color_to_rgb(item.color)
        page.insert_textbox(
            target_rect,
            item.text,
            fontsize=item.font_size,
            fontname=fontname,
            color=color,
            align=fitz.TEXT_ALIGN_JUSTIFY,
        )
        if item.op is not None:
            report["applied"] += 1


def _measure_overflow(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontsize: float,
    fontname: str,
    color: tuple[float, float, float],
) -> float:
    """Use TextWriter on a throwaway shape to measure required extra height."""
    tw = fitz.TextWriter(page.rect)
    used = tw.fill_textbox(
        rect,
        text,
        fontsize=fontsize,
        font=fitz.Font(fontname),
        align=fitz.TEXT_ALIGN_JUSTIFY,
    )
    if not used:
        return 0.0
    leftover = used if isinstance(used, str) else ""
    if not leftover:
        return 0.0
    avg_char_width = fontsize * 0.5 or 1.0
    chars_per_line = max(1, int(rect.width / avg_char_width))
    extra_lines = max(1, len(leftover) // chars_per_line + 1)
    return extra_lines * fontsize * 1.25


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
