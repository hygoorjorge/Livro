from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Figure,
    Mention,
    MentionStatus,
    Page,
    Paragraph,
    Proposal,
    ProposalStatus,
    Session,
    SessionStatus,
    TextSpan,
)
from app.db.session import get_session_dep
from app.services.docx_exporter import export_docx
from app.services.pdf_editor import EditOp, PageParagraph, apply_edits, replace_figure
from app.services.verifier import verify_session

router = APIRouter(prefix="/verify", tags=["verify"])


class VerifyOut(BaseModel):
    passed: bool
    total_diffs: int
    unauthorized_diffs: list[dict]


async def _build_edit_ops(
    db: AsyncSession, session_id: int
) -> tuple[list[EditOp], dict[int, list[PageParagraph]]]:
    pages = (
        await db.execute(
            select(Page).where(Page.session_id == session_id).order_by(Page.page_num)
        )
    ).scalars().all()
    page_by_id = {p.id: p for p in pages}
    page_ids = list(page_by_id.keys())

    spans_by_page: dict[int, list[TextSpan]] = {}
    if page_ids:
        rows = (
            await db.execute(
                select(TextSpan)
                .where(TextSpan.page_id.in_(page_ids))
                .order_by(TextSpan.page_id, TextSpan.span_index)
            )
        ).scalars().all()
        for s in rows:
            spans_by_page.setdefault(s.page_id, []).append(s)

    paragraphs = (
        await db.execute(
            select(Paragraph)
            .where(Paragraph.page_id.in_(page_ids))
            .order_by(Paragraph.page_id, Paragraph.paragraph_index)
        )
    ).scalars().all()

    layouts_by_page: dict[int, list[PageParagraph]] = {}
    para_by_id: dict[int, Paragraph] = {}
    for para in paragraphs:
        para_by_id[para.id] = para
        page = page_by_id.get(para.page_id)
        if page is None:
            continue
        spans = spans_by_page.get(page.id, [])
        para_spans = [s for s in spans if s.span_index in (para.span_ids_json or [])]
        if not para_spans:
            continue
        bboxes = [(s.bbox_x0, s.bbox_y0, s.bbox_x1, s.bbox_y1) for s in para_spans]
        dominant = max(para_spans, key=lambda s: len(s.text))
        layouts_by_page.setdefault(page.page_num, []).append(
            PageParagraph(
                paragraph_index=para.paragraph_index,
                text=para.full_text,
                span_bboxes=bboxes,
                font_name=dominant.font_name,
                font_size=dominant.font_size,
                color=dominant.color,
            )
        )

    proposals = (
        await db.execute(
            select(Proposal).where(
                Proposal.status.in_(
                    [ProposalStatus.accepted.value, ProposalStatus.edited.value]
                )
            )
        )
    ).scalars().all()

    ops: list[EditOp] = []
    for prop in proposals:
        mention = await db.get(Mention, prop.mention_id)
        if mention is None:
            continue
        para = para_by_id.get(mention.paragraph_id)
        if para is None:
            continue
        page = page_by_id.get(para.page_id)
        if page is None:
            continue
        spans = spans_by_page.get(page.id, [])
        para_spans = [s for s in spans if s.span_index in (para.span_ids_json or [])]
        if not para_spans:
            continue
        bboxes = [(s.bbox_x0, s.bbox_y0, s.bbox_x1, s.bbox_y1) for s in para_spans]
        dominant = max(para_spans, key=lambda s: len(s.text))
        new_full_text = para.full_text.replace(
            prop.original_text, prop.proposed_text, 1
        )
        ops.append(
            EditOp(
                page_num=page.page_num,
                paragraph_index=para.paragraph_index,
                original_text=para.full_text,
                final_text=new_full_text,
                span_bboxes=bboxes,
                font_name=dominant.font_name,
                font_size=dominant.font_size,
                color=dominant.color,
            )
        )
    return ops, layouts_by_page


@router.post("/{session_id}/export")
async def export(session_id: int, db: AsyncSession = Depends(get_session_dep)):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "session not found")

    pending = (
        await db.execute(
            select(Mention).where(Mention.status == MentionStatus.pending.value)
        )
    ).scalars().all()
    if pending:
        raise HTTPException(
            400, f"There are {len(pending)} pending mentions; resolve before export"
        )

    ops, layouts = await _build_edit_ops(db, session_id)
    output_pdf = settings.exports_dir / f"session_{session_id}.pdf"
    report = apply_edits(session.pdf_path, output_pdf, ops, layouts)

    figures = (
        await db.execute(
            select(Figure)
            .join(Page, Figure.page_id == Page.id)
            .where(
                Page.session_id == session_id,
                Figure.status == "replaced",
            )
        )
    ).scalars().all()
    for fig in figures:
        if not fig.replacement_path:
            continue
        page = await db.get(Page, fig.page_id)
        if page is None:
            continue
        replace_figure(
            output_pdf,
            output_pdf,
            page.page_num,
            (fig.bbox_x0, fig.bbox_y0, fig.bbox_x1, fig.bbox_y1),
            fig.replacement_path,
        )

    docx_path = settings.exports_dir / f"session_{session_id}.docx"
    await export_docx(db, session_id, docx_path)

    session.status = SessionStatus.exported.value
    return {
        "pdf": str(output_pdf),
        "docx": str(docx_path),
        "edit_report": report,
    }


@router.post("/{session_id}/run", response_model=VerifyOut)
async def run_verification(
    session_id: int, db: AsyncSession = Depends(get_session_dep)
):
    output_pdf = settings.exports_dir / f"session_{session_id}.pdf"
    if not output_pdf.exists():
        raise HTTPException(400, "Export the PDF before running verification")
    run = await verify_session(db, session_id, output_pdf)
    return VerifyOut(
        passed=run.passed,
        total_diffs=run.total_diffs,
        unauthorized_diffs=run.unauthorized_diffs_json,
    )
