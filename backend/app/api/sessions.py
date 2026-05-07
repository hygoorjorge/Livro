from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session, SessionStatus
from app.db.session import get_session_dep

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionOut(BaseModel):
    id: int
    name: str
    status: str
    pdf_path: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[SessionOut])
async def list_sessions(db: AsyncSession = Depends(get_session_dep)):
    rows = (await db.execute(select(Session).order_by(Session.created_at.desc()))).scalars().all()
    return rows


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, db: AsyncSession = Depends(get_session_dep)):
    s = await db.get(Session, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    return s


@router.post("/{session_id}/status")
async def set_status(
    session_id: int, status: str, db: AsyncSession = Depends(get_session_dep)
):
    s = await db.get(Session, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    if status not in {st.value for st in SessionStatus}:
        raise HTTPException(400, f"invalid status: {status}")
    s.status = status
    return {"id": s.id, "status": s.status}
