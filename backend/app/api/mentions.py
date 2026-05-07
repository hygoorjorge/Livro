from dataclasses import dataclass

import fitz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
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
from app.services.claude_client import ClaudeClient
from app.services.corpus import build_corpus, has_corpus
from app.services.mention_detector import context_window, find_candidates
from app.workers.progress import publish_progress

logger = get_logger(__name__)


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


@dataclass
class _Pending:
    paragraph_id: int
    char_start: int
    char_end: int
    raw_text: str
    detected_ref: str
    regex_historical: bool
    context: str


async def _detect(session_id: int, use_classifier: bool = True) -> None:
    """Two-phase detection: regex collects candidates, Claude validates them.

    The classifier filters false positives, normalizes references and refines
    the historical-context flag. If no laws/mappings are configured yet, or if
    the Anthropic key is missing, the function falls back to regex-only.
    """
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

        pending: list[_Pending] = []
        for i, para in enumerate(paragraphs, start=1):
            if para.protected:
                continue
            for cand in find_candidates(para.full_text):
                pending.append(
                    _Pending(
                        paragraph_id=para.id,
                        char_start=cand.char_start,
                        char_end=cand.char_end,
                        raw_text=cand.raw_text,
                        detected_ref=cand.detected_ref,
                        regex_historical=cand.has_historical_hint_nearby,
                        context=context_window(para.full_text, cand),
                    )
                )
            if i % 25 == 0 or i == total:
                await publish_progress(
                    session_id,
                    "detect_progress",
                    {"done": i, "total": total, "mentions": len(pending)},
                )

        classifier_active = use_classifier and bool(settings.anthropic_api_key)
        if classifier_active and pending:
            classifier_active = await has_corpus(db)
        if classifier_active:
            await _classify_and_persist(db, session_id, pending)
        else:
            logger.info(
                "classifier disabled (use=%s key=%s); persisting regex hits as-is",
                use_classifier,
                bool(settings.anthropic_api_key),
            )
            for p in pending:
                db.add(
                    Mention(
                        paragraph_id=p.paragraph_id,
                        char_start=p.char_start,
                        char_end=p.char_end,
                        raw_text=p.raw_text,
                        detected_ref=p.detected_ref,
                        is_historical=p.regex_historical,
                        classifier_confidence=0.0,
                        status=(
                            MentionStatus.awaiting_user_decision.value
                            if p.regex_historical
                            else MentionStatus.pending.value
                        ),
                    )
                )

        session.status = SessionStatus.reviewing.value
        await db.commit()
        await publish_progress(
            session_id,
            "detect_done",
            {"total": total, "mentions": len(pending), "classified": classifier_active},
        )


async def _classify_and_persist(
    db: AsyncSession, session_id: int, pending: list[_Pending]
) -> None:
    """Send pending regex hits through Claude in batches and persist results."""
    corpus = await build_corpus(db)
    claude = ClaudeClient()
    batch_size = settings.classifier_batch_size
    total_batches = (len(pending) + batch_size - 1) // batch_size

    kept = dropped = 0
    for batch_idx in range(total_batches):
        batch = pending[batch_idx * batch_size : (batch_idx + 1) * batch_size]
        candidates = [
            {
                "candidate_id": idx,
                "raw_text": p.raw_text,
                "detected_ref": p.detected_ref,
                "regex_historical": p.regex_historical,
                "context": p.context,
            }
            for idx, p in enumerate(batch)
        ]
        try:
            results = await claude.classify_candidates(
                law_corpus_block=corpus, candidates=candidates
            )
        except Exception as exc:
            logger.warning("classifier failed on batch %d: %s — falling back to regex", batch_idx, exc)
            results = []

        result_by_id = {r.candidate_id: r for r in results}
        for local_idx, p in enumerate(batch):
            r = result_by_id.get(local_idx)
            if r is not None and not r.is_mention:
                dropped += 1
                continue
            historical = (
                r.is_historical if r is not None else p.regex_historical
            )
            ref = (r.normalized_ref if r and r.normalized_ref else p.detected_ref)
            db.add(
                Mention(
                    paragraph_id=p.paragraph_id,
                    char_start=p.char_start,
                    char_end=p.char_end,
                    raw_text=p.raw_text,
                    detected_ref=ref,
                    is_historical=historical,
                    classifier_confidence=r.confidence if r else 0.0,
                    classifier_rationale=r.rationale if r else None,
                    status=(
                        MentionStatus.awaiting_user_decision.value
                        if historical
                        else MentionStatus.pending.value
                    ),
                )
            )
            kept += 1
        await publish_progress(
            session_id,
            "classify_progress",
            {
                "batch": batch_idx + 1,
                "total_batches": total_batches,
                "kept": kept,
                "dropped": dropped,
            },
        )


@router.post("/{session_id}/detect")
async def detect(
    session_id: int,
    background: BackgroundTasks,
    use_classifier: bool = True,
    db: AsyncSession = Depends(get_session_dep),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    background.add_task(_detect, session_id, use_classifier)
    return {"queued": True, "classifier": use_classifier}


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

    Uses PyMuPDF page.search_for(raw_text) for word-level tight bboxes.
    Falls back to the span bbox if search_for finds no match, and to the
    paragraph-union bbox as a last resort.
    """
    session_row = await db.get(Session, session_id)

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

    # Open the original PDF once so we can use page.search_for() per mention.
    fitz_doc: fitz.Document | None = None
    fitz_pages: dict[int, fitz.Page] = {}  # keyed by 0-based page index
    if session_row and session_row.pdf_path:
        try:
            fitz_doc = fitz.open(session_row.pdf_path)
        except Exception:
            fitz_doc = None

    def _fitz_page(page_num: int) -> fitz.Page | None:
        """Return (and cache) a fitz page by 1-based page number."""
        if fitz_doc is None:
            return None
        idx = page_num - 1
        if idx < 0 or idx >= fitz_doc.page_count:
            return None
        if idx not in fitz_pages:
            fitz_pages[idx] = fitz_doc[idx]
        return fitz_pages[idx]

    def _tight_bbox(
        raw_text: str,
        page_num: int,
        para_spans: list[TextSpan],
    ) -> tuple[float, float, float, float] | None:
        """Return a word-level bbox from search_for, or None if not found."""
        fp = _fitz_page(page_num)
        if fp is None:
            return None
        hits = fp.search_for(raw_text, quads=False)
        if not hits:
            return None
        # Para center used to pick the closest hit when there are multiple matches
        # (e.g. the same bill number appears twice on the page).
        para_cx = (
            min(s.bbox_x0 for s in para_spans) + max(s.bbox_x1 for s in para_spans)
        ) / 2
        para_cy = (
            min(s.bbox_y0 for s in para_spans) + max(s.bbox_y1 for s in para_spans)
        ) / 2
        best: fitz.Rect = min(
            hits,
            key=lambda r: abs((r.x0 + r.x1) / 2 - para_cx)
            + abs((r.y0 + r.y1) / 2 - para_cy),
        )
        return (best.x0, best.y0, best.x1, best.y1)

    out: list[HighlightOut] = []
    try:
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

            # 1st choice: tight bbox via PDF text search
            bbox: tuple[float, float, float, float] | None = _tight_bbox(
                m.raw_text, page.page_num, para_spans
            )

            if bbox is None:
                # 2nd choice: span that contains anchor text
                anchor = m.detected_ref.split()[-1].split("/")[0]
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
                    # Last resort: union of all paragraph spans
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
    finally:
        if fitz_doc is not None:
            fitz_doc.close()

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
