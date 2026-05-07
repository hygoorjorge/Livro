from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Mention, MentionStatus, Page, Paragraph, Session, SessionStatus
from app.db.session import SessionLocal, get_session_dep
from app.services.claude_client import ClaudeClient, build_law_corpus_block
from app.services.mention_detector import find_candidates


router = APIRouter(prefix="/mentions", tags=["mentions"])


class MentionOut(BaseModel):
    id: int
    paragraph_id: int
    raw_text: str
    detected_ref: str
    is_historical: bool
    classifier_confidence: float
    status: str

    class Config:
        from_attributes = True


async def _detect(session_id: int) -> None:
    async with SessionLocal() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        pages = (
            await db.execute(select(Page).where(Page.session_id == session_id))
        ).scalars().all()
        page_ids = [p.id for p in pages]
        paragraphs = (
            await db.execute(select(Paragraph).where(Paragraph.page_id.in_(page_ids)))
        ).scalars().all()
        for para in paragraphs:
            if para.protected:
                continue
            for cand in find_candidates(para.full_text):
                db.add(
                    Mention(
                        paragraph_id=para.id,
                        char_start=cand.char_start,
                        char_end=cand.char_end,
                        raw_text=cand.raw_text,
                        detected_ref=cand.detected_ref,
                        is_historical=cand.has_historical_hint_nearby,
                        status=MentionStatus.pending.value,
                    )
                )
        session.status = SessionStatus.reviewing.value
        await db.commit()


@router.post("/{session_id}/detect")
async def detect(
    session_id: int,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_session_dep),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    background.add_task(_detect, session_id)
    return {"queued": True}


@router.get("/{session_id}", response_model=list[MentionOut])
async def list_mentions(
    session_id: int,
    status: str | None = None,
    db: AsyncSession = Depends(get_session_dep),
):
    pages = (
        await db.execute(select(Page).where(Page.session_id == session_id))
    ).scalars().all()
    page_ids = [p.id for p in pages]
    paragraphs = (
        await db.execute(select(Paragraph).where(Paragraph.page_id.in_(page_ids)))
    ).scalars().all()
    para_ids = [p.id for p in paragraphs]
    q = select(Mention).where(Mention.paragraph_id.in_(para_ids))
    if status:
        q = q.where(Mention.status == status)
    return (await db.execute(q)).scalars().all()
