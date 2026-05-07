"""Final line-by-line check: every diff must be covered by an accepted proposal."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Mention,
    MentionStatus,
    Page,
    Paragraph,
    Proposal,
    ProposalStatus,
    VerificationRun,
)
from app.services.pdf_parser import parse_pdf


@dataclass
class UnauthorizedDiff:
    paragraph_index: int
    page_num: int
    original: str
    final: str


async def verify_session(
    db: AsyncSession, session_id: int, edited_pdf: str | Path
) -> VerificationRun:
    accepted = (
        await db.execute(
            select(Proposal).where(
                Proposal.status.in_(
                    [ProposalStatus.accepted.value, ProposalStatus.edited.value]
                )
            )
        )
    ).scalars().all()

    authorized_by_paragraph: dict[int, list[tuple[str, str]]] = {}
    for prop in accepted:
        mention = await db.get(Mention, prop.mention_id)
        if mention is None:
            continue
        authorized_by_paragraph.setdefault(mention.paragraph_id, []).append(
            (prop.original_text, prop.proposed_text)
        )

    pending = (
        await db.execute(
            select(Mention).where(Mention.status == MentionStatus.pending.value)
        )
    ).scalars().all()

    parsed_final = parse_pdf(str(edited_pdf))
    page_rows = (
        await db.execute(
            select(Page).where(Page.session_id == session_id).order_by(Page.page_num)
        )
    ).scalars().all()

    unauthorized: list[UnauthorizedDiff] = []
    total_diffs = 0

    for page in page_rows:
        original_paras = (
            await db.execute(
                select(Paragraph)
                .where(Paragraph.page_id == page.id)
                .order_by(Paragraph.paragraph_index)
            )
        ).scalars().all()
        final_page = next(
            (p for p in parsed_final if p.page_num == page.page_num), None
        )
        final_by_idx = (
            {p.paragraph_index: p.full_text for p in final_page.paragraphs}
            if final_page
            else {}
        )

        for para in original_paras:
            final_text = final_by_idx.get(para.paragraph_index, "")
            if final_text == para.full_text:
                continue
            total_diffs += 1
            authorized_changes = authorized_by_paragraph.get(para.id, [])
            mutated = para.full_text
            for orig, new in authorized_changes:
                mutated = mutated.replace(orig, new, 1)
            if mutated.strip() != final_text.strip():
                unauthorized.append(
                    UnauthorizedDiff(
                        paragraph_index=para.paragraph_index,
                        page_num=page.page_num,
                        original=para.full_text,
                        final=final_text,
                    )
                )

    passed = not unauthorized and not pending

    run = VerificationRun(
        session_id=session_id,
        total_diffs=total_diffs,
        unauthorized_diffs_json=[
            {
                "page_num": u.page_num,
                "paragraph_index": u.paragraph_index,
                "diff": list(
                    difflib.ndiff(u.original.splitlines(), u.final.splitlines())
                ),
            }
            for u in unauthorized
        ],
        passed=passed,
    )
    db.add(run)
    return run
