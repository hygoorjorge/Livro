"""Generate update proposals for detected mentions.

Glue between the mention store, the law corpus, and ``ClaudeClient``. Persists
proposals back into the SQLite session.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    ChangeLog,
    Mention,
    MentionStatus,
    Page,
    Paragraph,
    Proposal,
    ProposalStatus,
)
from app.services.claude_client import ClaudeClient
from app.services.corpus import build_corpus

logger = get_logger(__name__)


async def _neighbor_paragraphs(db: AsyncSession, paragraph: Paragraph) -> list[str]:
    page = await db.get(Page, paragraph.page_id)
    if page is None:
        return []
    rows = (
        await db.execute(
            select(Paragraph)
            .where(Paragraph.page_id == page.id)
            .order_by(Paragraph.paragraph_index)
        )
    ).scalars().all()
    out: list[str] = []
    for row in rows:
        if abs(row.paragraph_index - paragraph.paragraph_index) == 1:
            out.append(row.full_text)
    return out


async def generate_proposal(
    db: AsyncSession, mention_id: int, claude: ClaudeClient
) -> Proposal:
    mention = await db.get(Mention, mention_id)
    if mention is None:
        raise ValueError(f"Mention {mention_id} not found")
    paragraph = await db.get(Paragraph, mention.paragraph_id)
    if paragraph is None:
        raise ValueError(f"Paragraph for mention {mention_id} not found")
    if paragraph.protected:
        raise ValueError("Cannot propose changes on protected paragraph")

    corpus = await build_corpus(db)
    neighbors = await _neighbor_paragraphs(db, paragraph)

    result = await claude.propose_update(
        law_corpus_block=corpus,
        paragraph_text=paragraph.full_text,
        mention_raw=mention.raw_text,
        mention_ref=mention.detected_ref,
        neighbor_paragraphs=neighbors,
    )

    proposal = Proposal(
        mention_id=mention.id,
        mode="auto",
        original_text=result.original_excerpt,
        proposed_text=result.proposed_excerpt,
        justification=result.justification,
        claude_model=result.model,
        prompt_cache_hit=result.cache_hit,
        needs_human_check=result.needs_human_check,
        confidence=result.confidence,
        status=ProposalStatus.pending.value,
    )
    db.add(proposal)
    await db.flush()

    page = await db.get(Page, paragraph.page_id)
    session_id = page.session_id if page else 0
    db.add(
        ChangeLog(
            session_id=session_id,
            kind="proposal_generated",
            ref_id=proposal.id,
            before=result.original_excerpt,
            after=result.proposed_excerpt,
            actor="claude:auto",
        )
    )

    if result.is_historical_context:
        mention.status = MentionStatus.awaiting_user_decision.value
    return proposal


async def accept_proposal(
    db: AsyncSession, proposal_id: int, edited_text: str | None = None
) -> Proposal:
    proposal = await db.get(Proposal, proposal_id)
    if proposal is None:
        raise ValueError(f"Proposal {proposal_id} not found")
    final_text = edited_text if edited_text is not None else proposal.proposed_text
    proposal.proposed_text = final_text
    proposal.status = (
        ProposalStatus.edited.value
        if edited_text is not None
        else ProposalStatus.accepted.value
    )

    mention = await db.get(Mention, proposal.mention_id)
    paragraph = await db.get(Paragraph, mention.paragraph_id) if mention else None
    page = await db.get(Page, paragraph.page_id) if paragraph else None
    db.add(
        ChangeLog(
            session_id=page.session_id if page else 0,
            kind="proposal_accepted",
            ref_id=proposal.id,
            before=proposal.original_text,
            after=final_text,
            actor="user",
        )
    )
    return proposal


async def reject_proposal(db: AsyncSession, proposal_id: int) -> Proposal:
    proposal = await db.get(Proposal, proposal_id)
    if proposal is None:
        raise ValueError(f"Proposal {proposal_id} not found")
    proposal.status = ProposalStatus.rejected.value
    mention = await db.get(Mention, proposal.mention_id)
    paragraph = await db.get(Paragraph, mention.paragraph_id) if mention else None
    page = await db.get(Page, paragraph.page_id) if paragraph else None
    db.add(
        ChangeLog(
            session_id=page.session_id if page else 0,
            kind="proposal_rejected",
            ref_id=proposal.id,
            before=proposal.original_text,
            after=proposal.proposed_text,
            actor="user",
        )
    )
    return proposal
