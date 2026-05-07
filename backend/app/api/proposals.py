from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Mention, Page, Paragraph, Proposal, ProposalStatus
from app.db.session import get_session_dep
from app.services.claude_client import ClaudeClient
from app.services.proposal_engine import accept_proposal, generate_proposal, reject_proposal

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
