from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChangeLog,
    Mention,
    MentionStatus,
    Page,
    Paragraph,
    Session,
    SessionStatus,
    TextSpan,
)
from app.db.session import SessionLocal, get_session_dep
from app.services.mention_detector import find_candidates
from app.workers.progress import publish_progress


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


class HighlightOut(BaseModel):
    mention_id: int
    page_num: int
    bbox: tuple[float, float, float, float]
    raw_text: str
    detected_ref: str
    is_historical: bool
    status: str
    paragraph_id: int


class StatusIn(BaseModel):
    status: str


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
        total = len(paragraphs)
        await publish_progress(session_id, "detect_start", {"total": total})
        found = 0
        for i, para in enumerate(paragraphs, start=1):
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
                        status=(
                            MentionStatus.awaiting_user_decision.value
                            if cand.has_historical_hint_nearby
                            else MentionStatus.pending.value
                        ),
                    )
                )
                found += 1
            if i % 25 == 0 or i == total:
                await publish_progress(
                    session_id,
                    "detect_progress",
                    {"done": i, "total": total, "mentions": found},
                )
        session.status = SessionStatus.reviewing.value
        await db.commit()
        await publish_progress(
            session_id, "detect_done", {"total": total, "mentions": found}
        )


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


@router.get("/{session_id}/highlights", response_model=list[HighlightOut])
async def list_highlights(
    session_id: int, db: AsyncSession = Depends(get_session_dep)
):
    """Return mention positions for the PDF.js overlay.

    For each mention, picks the bbox of the span that contains the matched
    text (anchored on the normalized number, e.g. "108") so the highlight is
    tight. Falls back to the paragraph-union bbox if no single span matches.
    """
    pages = (
        await db.execute(
            select(Page).where(Page.session_id == session_id).order_by(Page.page_num)
        )
    ).scalars().all()
    page_by_id = {p.id: p for p in pages}
    page_ids = list(page_by_id.keys())
    if not page_ids:
        return []

    paragraphs = (
        await db.execute(
            select(Paragraph).where(Paragraph.page_id.in_(page_ids))
        )
    ).scalars().all()
    para_by_id = {p.id: p for p in paragraphs}

    spans_by_page: dict[int, list[TextSpan]] = {}
    rows = (
        await db.execute(
            select(TextSpan)
            .where(TextSpan.page_id.in_(page_ids))
            .order_by(TextSpan.page_id, TextSpan.span_index)
        )
    ).scalars().all()
    for s in rows:
        spans_by_page.setdefault(s.page_id, []).append(s)

    para_ids = list(para_by_id.keys())
    mentions = (
        await db.execute(
            select(Mention)
            .where(Mention.paragraph_id.in_(para_ids))
            .where(Mention.status != MentionStatus.dismissed.value)
        )
    ).scalars().all()

    out: list[HighlightOut] = []
    for m in mentions:
        para = para_by_id.get(m.paragraph_id)
        if para is None:
            continue
        page = page_by_id.get(para.page_id)
        if page is None:
            continue
        spans = spans_by_page.get(page.id, [])
        para_span_set = set(para.span_ids_json or [])
        para_spans = [s for s in spans if s.span_index in para_span_set]
        if not para_spans:
            continue

        anchor = m.detected_ref.split()[-1].split("/")[0]
        bbox: tuple[float, float, float, float]
        candidate = next(
            (s for s in para_spans if anchor in s.text or m.raw_text in s.text),
            None,
        )
        if candidate is not None:
            bbox = (
                candidate.bbox_x0,
                candidate.bbox_y0,
                candidate.bbox_x1,
                candidate.bbox_y1,
            )
        else:
            bbox = (
                min(s.bbox_x0 for s in para_spans),
                min(s.bbox_y0 for s in para_spans),
                max(s.bbox_x1 for s in para_spans),
                max(s.bbox_y1 for s in para_spans),
            )
        out.append(
            HighlightOut(
                mention_id=m.id,
                page_num=page.page_num,
                bbox=bbox,
                raw_text=m.raw_text,
                detected_ref=m.detected_ref,
                is_historical=m.is_historical,
                status=m.status,
                paragraph_id=m.paragraph_id,
            )
        )
    return out


@router.post("/{mention_id}/status", response_model=MentionOut)
async def set_mention_status(
    mention_id: int,
    payload: StatusIn,
    db: AsyncSession = Depends(get_session_dep),
):
    if payload.status not in {s.value for s in MentionStatus}:
        raise HTTPException(400, f"invalid status: {payload.status}")
    mention = await db.get(Mention, mention_id)
    if mention is None:
        raise HTTPException(404, "mention not found")
    before = mention.status
    mention.status = payload.status
    para = await db.get(Paragraph, mention.paragraph_id)
    page = await db.get(Page, para.page_id) if para else None
    db.add(
        ChangeLog(
            session_id=page.session_id if page else 0,
            kind="mention_status",
            ref_id=mention.id,
            before=before,
            after=mention.status,
            actor="user",
        )
    )
    return mention
