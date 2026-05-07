import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    Mention,
    MentionStatus,
    Page,
    Paragraph,
    Proposal,
    ProposalStatus,
)
from app.db.session import SessionLocal, get_session_dep
from app.services.claude_client import ClaudeClient
from app.services.proposal_engine import (
    accept_proposal,
    generate_proposal,
    reject_proposal,
)
from app.workers.progress import publish_progress

logger = get_logger(__name__)

router = APIRouter(prefix="/proposals", tags=["proposals"])


class ProposalOut(BaseModel):
    id: int
    mention_id: int
    mode: str
    original_text: str
    proposed_text: str
    justification: str | None
    confidence: float
    needs_human_check: bool
    status: str
    prompt_cache_hit: bool

    class Config:
        from_attributes = True


class AcceptIn(BaseModel):
    edited_text: str | None = None


class ManualIn(BaseModel):
    mention_id: int
    final_text: str


@router.post("/auto/{mention_id}", response_model=ProposalOut)
async def generate_auto(
    mention_id: int, db: AsyncSession = Depends(get_session_dep)
):
    claude = ClaudeClient()
    proposal = await generate_proposal(db, mention_id, claude)
    return proposal


@router.post("/manual", response_model=ProposalOut)
async def generate_manual(
    payload: ManualIn, db: AsyncSession = Depends(get_session_dep)
):
    mention = await db.get(Mention, payload.mention_id)
    if mention is None:
        raise HTTPException(404, "mention not found")
    paragraph = await db.get(Paragraph, mention.paragraph_id)
    proposal = Proposal(
        mention_id=payload.mention_id,
        mode="manual",
        original_text=paragraph.full_text if paragraph else "",
        proposed_text=payload.final_text,
        justification="Edição manual",
        prompt_cache_hit=False,
        status=ProposalStatus.accepted.value,
        confidence=1.0,
    )
    db.add(proposal)
    await db.flush()
    return proposal


@router.post("/{proposal_id}/accept", response_model=ProposalOut)
async def accept(
    proposal_id: int,
    payload: AcceptIn,
    db: AsyncSession = Depends(get_session_dep),
):
    return await accept_proposal(db, proposal_id, payload.edited_text)


@router.post("/{proposal_id}/reject", response_model=ProposalOut)
async def reject(proposal_id: int, db: AsyncSession = Depends(get_session_dep)):
    return await reject_proposal(db, proposal_id)


@router.get("/by-mention/{mention_id}", response_model=list[ProposalOut])
async def list_for_mention(
    mention_id: int, db: AsyncSession = Depends(get_session_dep)
):
    rows = (
        await db.execute(select(Proposal).where(Proposal.mention_id == mention_id))
    ).scalars().all()
    return rows


async def _generate_batch(session_id: int) -> None:
    claude = ClaudeClient()
    async with SessionLocal() as db:
        pages = (
            await db.execute(select(Page).where(Page.session_id == session_id))
        ).scalars().all()
        page_ids = [p.id for p in pages]
        paragraphs = (
            await db.execute(
                select(Paragraph).where(Paragraph.page_id.in_(page_ids))
            )
        ).scalars().all()
        para_ids = [p.id for p in paragraphs]
        mentions = (
            await db.execute(
                select(Mention)
                .where(Mention.paragraph_id.in_(para_ids))
                .where(Mention.status == MentionStatus.pending.value)
            )
        ).scalars().all()
        existing = (
            await db.execute(
                select(Proposal.mention_id).where(
                    Proposal.mention_id.in_([m.id for m in mentions])
                )
            )
        ).scalars().all()
        already = set(existing)
        targets = [m.id for m in mentions if m.id not in already]

    total = len(targets)
    await publish_progress(
        session_id, "batch_proposal_start", {"total": total}
    )
    if not total:
        await publish_progress(session_id, "batch_proposal_done", {"total": 0})
        return

    semaphore = asyncio.Semaphore(3)
    completed = 0

    async def _one(mid: int) -> None:
        nonlocal completed
        async with semaphore:
            try:
                async with SessionLocal() as db:
                    await generate_proposal(db, mid, claude)
                    await db.commit()
            except Exception as exc:
                logger.warning("batch proposal failed for mention %d: %s", mid, exc)
            finally:
                completed += 1
                await publish_progress(
                    session_id,
                    "batch_proposal_progress",
                    {"done": completed, "total": total},
                )

    await asyncio.gather(*(_one(mid) for mid in targets))
    await publish_progress(
        session_id, "batch_proposal_done", {"total": total, "done": completed}
    )


@router.post("/{session_id}/batch")
async def batch_generate(
    session_id: int,
    background: BackgroundTasks,
):
    background.add_task(_generate_batch, session_id)
    return {"queued": True}
