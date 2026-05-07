from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Figure, FigureStatus, Page
from app.db.session import get_session_dep
from app.services.figure_detector import flag_suspicious_figures

router = APIRouter(prefix="/figures", tags=["figures"])


class FigureOut(BaseModel):
    id: int
    page_id: int
    caption_text: str | None
    suspicion_reason: str | None
    status: str
    replacement_path: str | None

    class Config:
        from_attributes = True


@router.post("/{session_id}/scan")
async def scan(session_id: int, db: AsyncSession = Depends(get_session_dep)):
    flagged = await flag_suspicious_figures(db, session_id)
    return {"flagged": flagged}


@router.get("/{session_id}", response_model=list[FigureOut])
async def list_figures(
    session_id: int, db: AsyncSession = Depends(get_session_dep)
):
    pages = (
        await db.execute(select(Page).where(Page.session_id == session_id))
    ).scalars().all()
    page_ids = [p.id for p in pages]
    rows = (
        await db.execute(select(Figure).where(Figure.page_id.in_(page_ids)))
    ).scalars().all()
    return rows


@router.post("/{figure_id}/keep", response_model=FigureOut)
async def keep_figure(figure_id: int, db: AsyncSession = Depends(get_session_dep)):
    fig = await db.get(Figure, figure_id)
    if fig is None:
        raise HTTPException(404, "figure not found")
    fig.status = FigureStatus.kept.value
    return fig


@router.post("/{figure_id}/replace", response_model=FigureOut)
async def replace_figure(
    figure_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session_dep),
):
    fig = await db.get(Figure, figure_id)
    if fig is None:
        raise HTTPException(404, "figure not found")
    target = settings.uploads_dir / f"figure_{figure_id}_{file.filename}"
    target.write_bytes(await file.read())
    fig.status = FigureStatus.replaced.value
    fig.replacement_path = str(target)
    return fig
