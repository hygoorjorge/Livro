"""Parse PDF into spans, paragraphs and figures using PyMuPDF.

Output is structured to match the SQLite schema in ``app.db.models``. The
parser does not write to the DB itself; it returns plain dataclasses so it can
be unit-tested independently.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from app.db.models import ParagraphKind

BBox = tuple[float, float, float, float]

HYPHEN_RE = re.compile(r"(\w)-\n(\w)")


@dataclass
class ParsedSpan:
    span_index: int
    text: str
    bbox: BBox
    font_name: str
    font_size: float
    color: int
    flags: int


@dataclass
class ParsedParagraph:
    paragraph_index: int
    span_indices: list[int]
    full_text: str
    kind: ParagraphKind = ParagraphKind.body


@dataclass
class ParsedFigure:
    bbox: BBox
    image_hash: str
    caption_text: str | None = None


@dataclass
class ParsedPage:
    page_num: int
    width: float
    height: float
    spans: list[ParsedSpan] = field(default_factory=list)
    paragraphs: list[ParsedParagraph] = field(default_factory=list)
    figures: list[ParsedFigure] = field(default_factory=list)


def _dehyphenate(text: str) -> str:
    return HYPHEN_RE.sub(r"\1\2", text)


def _dominant_font_size(spans: list[ParsedSpan]) -> float:
    if not spans:
        return 0.0
    sizes: dict[float, int] = {}
    for s in spans:
        sizes[s.font_size] = sizes.get(s.font_size, 0) + len(s.text)
    return max(sizes.items(), key=lambda kv: kv[1])[0]


def _classify_paragraph(
    spans: list[ParsedSpan],
    page: ParsedPage,
    body_size: float,
) -> ParagraphKind:
    if not spans:
        return ParagraphKind.unknown
    avg_size = sum(s.font_size for s in spans) / len(spans)
    top_y = min(s.bbox[1] for s in spans)
    bottom_y = max(s.bbox[3] for s in spans)
    left_x = min(s.bbox[0] for s in spans)
    text = " ".join(s.text for s in spans).strip()

    page_h = page.height or 1.0
    if top_y < page_h * 0.06:
        return ParagraphKind.header
    if bottom_y > page_h * 0.94:
        return ParagraphKind.footer

    if body_size and avg_size <= body_size * 0.85:
        if re.match(r"^\d+\s", text) or re.match(r"^\(\d+\)", text):
            return ParagraphKind.footnote
        return ParagraphKind.footnote

    if re.search(r"\.\s*\.\s*\.\s*\.+\s*\d+\s*$", text):
        return ParagraphKind.toc

    if left_x > (page.width or 1.0) * 0.18 and len(text) > 80:
        return ParagraphKind.block_quote

    if re.match(r"^(figura|tabela|gr[aá]fico|quadro)\s+\d+", text, re.IGNORECASE):
        return ParagraphKind.caption

    return ParagraphKind.body


def _group_paragraphs(spans: list[ParsedSpan]) -> list[list[int]]:
    """Group spans into paragraphs by reading order + vertical gaps."""
    if not spans:
        return []
    sorted_idx = sorted(
        range(len(spans)),
        key=lambda i: (round(spans[i].bbox[1] / 2), spans[i].bbox[0]),
    )
    groups: list[list[int]] = []
    current: list[int] = []
    last_bottom: float | None = None
    for idx in sorted_idx:
        s = spans[idx]
        if last_bottom is None:
            current = [idx]
        else:
            gap = s.bbox[1] - last_bottom
            if gap > s.font_size * 0.8:
                if current:
                    groups.append(current)
                current = [idx]
            else:
                current.append(idx)
        last_bottom = max(last_bottom or s.bbox[3], s.bbox[3])
    if current:
        groups.append(current)
    return groups


def _figure_caption(page: ParsedPage, fig_bbox: BBox) -> str | None:
    candidates: list[ParsedParagraph] = []
    fy1 = fig_bbox[3]
    for para in page.paragraphs:
        if para.kind != ParagraphKind.caption:
            continue
        para_top = min(page.spans[i].bbox[1] for i in para.span_indices)
        if 0 <= para_top - fy1 <= 60:
            candidates.append(para)
    if not candidates:
        return None
    return candidates[0].full_text


def parse_pdf(path: str | Path) -> list[ParsedPage]:
    doc = fitz.open(str(path))
    pages: list[ParsedPage] = []
    try:
        for page_num, page in enumerate(doc, start=1):
            parsed = ParsedPage(page_num=page_num, width=page.rect.width, height=page.rect.height)

            raw = page.get_text("dict")
            span_idx = 0
            for block in raw.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if not text.strip():
                            continue
                        parsed.spans.append(
                            ParsedSpan(
                                span_index=span_idx,
                                text=text,
                                bbox=tuple(span["bbox"]),
                                font_name=span.get("font", ""),
                                font_size=float(span.get("size", 0.0)),
                                color=int(span.get("color", 0)),
                                flags=int(span.get("flags", 0)),
                            )
                        )
                        span_idx += 1

            body_size = _dominant_font_size(parsed.spans)
            for p_idx, span_indices in enumerate(_group_paragraphs(parsed.spans)):
                group_spans = [parsed.spans[i] for i in span_indices]
                raw_text = " ".join(s.text for s in group_spans)
                full_text = _dehyphenate(raw_text).strip()
                kind = _classify_paragraph(group_spans, parsed, body_size)
                parsed.paragraphs.append(
                    ParsedParagraph(
                        paragraph_index=p_idx,
                        span_indices=span_indices,
                        full_text=full_text,
                        kind=kind,
                    )
                )

            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    rects = []
                pix = fitz.Pixmap(doc, xref)
                img_hash = hashlib.sha1(pix.samples).hexdigest()
                pix = None
                for rect in rects or [page.rect]:
                    bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                    fig = ParsedFigure(bbox=bbox, image_hash=img_hash)
                    fig.caption_text = _figure_caption(parsed, bbox)
                    parsed.figures.append(fig)

            pages.append(parsed)
    finally:
        doc.close()
    return pages


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
