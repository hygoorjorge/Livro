import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    ChangeLog,
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
    VerificationRun,
)
from app.db.session import get_session_dep
from app.services.audit_pdf_exporter import export_audit_pdf
from app.services.docx_exporter import export_docx
from app.services.pdf_editor import EditOp, PageParagraph, apply_edits, replace_figure
from app.services.pdf_parser import file_sha256
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

    session.hash_final = file_sha256(output_pdf)
    session.status = SessionStatus.exported.value
    return {
        "pdf": str(output_pdf),
        "docx": str(docx_path),
        "edit_report": report,
        "hash_original": session.hash_original,
        "hash_final": session.hash_final,
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


async def _collect_audit(
    db: AsyncSession, session_id: int
) -> dict:
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "session not found")

    log_rows = (
        await db.execute(
            select(ChangeLog)
            .where(ChangeLog.session_id == session_id)
            .order_by(ChangeLog.ts)
        )
    ).scalars().all()

    proposals = (
        await db.execute(
            select(Proposal)
            .join(Mention, Proposal.mention_id == Mention.id)
            .join(Paragraph, Mention.paragraph_id == Paragraph.id)
            .join(Page, Paragraph.page_id == Page.id)
            .where(Page.session_id == session_id)
        )
    ).scalars().all()

    runs = (
        await db.execute(
            select(VerificationRun)
            .where(VerificationRun.session_id == session_id)
            .order_by(VerificationRun.ts)
        )
    ).scalars().all()

    return {
        "session": {
            "id": session.id,
            "name": session.name,
            "status": session.status,
            "hash_original": session.hash_original,
            "hash_final": session.hash_final,
            "pdf_path": session.pdf_path,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        },
        "proposals": [
            {
                "id": p.id,
                "mention_id": p.mention_id,
                "mode": p.mode,
                "status": p.status,
                "claude_model": p.claude_model,
                "prompt_cache_hit": p.prompt_cache_hit,
                "needs_human_check": p.needs_human_check,
                "confidence": p.confidence,
                "original": p.original_text,
                "proposed": p.proposed_text,
                "justification": p.justification,
            }
            for p in proposals
        ],
        "change_log": [
            {
                "id": e.id,
                "kind": e.kind,
                "ref_id": e.ref_id,
                "actor": e.actor,
                "ts": e.ts.isoformat(),
                "before": e.before,
                "after": e.after,
            }
            for e in log_rows
        ],
        "verification_runs": [
            {
                "id": r.id,
                "ts": r.ts.isoformat(),
                "passed": r.passed,
                "total_diffs": r.total_diffs,
                "unauthorized_diffs": r.unauthorized_diffs_json,
            }
            for r in runs
        ],
    }


@router.get("/{session_id}/audit.pdf")
async def audit_pdf(session_id: int, db: AsyncSession = Depends(get_session_dep)):
    payload = await _collect_audit(db, session_id)
    output_path = settings.exports_dir / f"audit_session_{session_id}.pdf"
    export_audit_pdf(payload, output_path)
    return FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=f"auditoria_sessao_{session_id}.pdf",
    )


@router.get("/{session_id}/audit.json")
async def audit_json(session_id: int, db: AsyncSession = Depends(get_session_dep)):
    return await _collect_audit(db, session_id)


@router.get("/{session_id}/audit.md")
async def audit_markdown(
    session_id: int, db: AsyncSession = Depends(get_session_dep)
):
    payload = await _collect_audit(db, session_id)
    s = payload["session"]
    lines: list[str] = [
        f"# Relatório de auditoria — sessão {s['id']}",
        "",
        f"- **Nome:** {s['name']}",
        f"- **Status:** {s['status']}",
        f"- **Hash original (sha256):** `{s['hash_original'] or '—'}`",
        f"- **Hash final (sha256):** `{s['hash_final'] or '—'}`",
        f"- **Criado em:** {s['created_at']}",
        f"- **Atualizado em:** {s['updated_at']}",
        "",
        f"## Propostas ({len(payload['proposals'])})",
        "",
    ]
    for p in payload["proposals"]:
        lines.extend(
            [
                f"### Proposta {p['id']} — {p['status']} ({p['mode']})",
                f"- modelo: `{p['claude_model']}` | cache: {'sim' if p['prompt_cache_hit'] else 'não'}",
                f"- confiança: {p['confidence']:.2f} | revisão humana: {'sim' if p['needs_human_check'] else 'não'}",
                "",
                "**Original:**",
                "",
                "```",
                p["original"] or "",
                "```",
                "",
                "**Proposto:**",
                "",
                "```",
                p["proposed"] or "",
                "```",
                "",
                f"**Justificativa:** {p['justification'] or '—'}",
                "",
                "---",
                "",
            ]
        )
    lines.extend(
        [
            f"## Verificações ({len(payload['verification_runs'])})",
            "",
        ]
    )
    for r in payload["verification_runs"]:
        status = "✅ passou" if r["passed"] else "❌ falhou"
        lines.append(
            f"- {r['ts']}: {status} ({r['total_diffs']} diffs, {len(r['unauthorized_diffs'])} não-autorizados)"
        )
    lines.extend(["", f"## Change log ({len(payload['change_log'])})", ""])
    for entry in payload["change_log"]:
        lines.append(
            f"- `{entry['ts']}` **{entry['kind']}** ref={entry['ref_id']} actor={entry['actor']}"
        )
    body = "\n".join(lines).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="audit_session_{session_id}.md"'
        },
    )
