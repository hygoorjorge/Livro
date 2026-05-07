"""Heuristics to flag figures that may be outdated by accepted updates."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChangeLog,
    Figure,
    FigureStatus,
    Page,
    Paragraph,
    Proposal,
    ProposalStatus,
)


SUSPICION_TERMS = (
    "PLP",
    "Projeto de Lei Complementar",
    "Reforma Tributária",
    "tramitação",
    "IBS",
    "CBS",
)


async def flag_suspicious_figures(db: AsyncSession, session_id: int) -> int:
    pages = (
        await db.execute(select(Page).where(Page.session_id == session_id))
    ).scalars().all()
    page_ids = [p.id for p in pages]
    if not page_ids:
        return 0

    accepted_paragraph_ids: set[int] = set()
    rows = (
        await db.execute(
            select(Proposal).where(
                Proposal.status.in_(
                    [ProposalStatus.accepted.value, ProposalStatus.edited.value]
                )
            )
        )
    ).scalars().all()
    for prop in rows:
        accepted_paragraph_ids.add(prop.mention.paragraph_id) if prop.mention else None

    figures = (
        await db.execute(select(Figure).where(Figure.page_id.in_(page_ids)))
    ).scalars().all()

    flagged = 0
    for fig in figures:
        if fig.status != FigureStatus.pending.value:
            continue
        reasons: list[str] = []
        caption = (fig.caption_text or "").lower()
        if any(t.lower() in caption for t in SUSPICION_TERMS):
            reasons.append("legenda menciona termos da reforma tributária")

        nearby_paragraphs = (
            await db.execute(
                select(Paragraph).where(Paragraph.page_id == fig.page_id)
            )
        ).scalars().all()
        for p in nearby_paragraphs:
            if p.id in accepted_paragraph_ids:
                reasons.append("parágrafo da mesma página foi atualizado")
                break

        if reasons:
            fig.suspicion_reason = "; ".join(reasons)
            db.add(
                ChangeLog(
                    session_id=session_id,
                    kind="figure_flagged",
                    ref_id=fig.id,
                    before=None,
                    after=fig.suspicion_reason,
                    actor="system",
                )
            )
            flagged += 1
    return flagged
