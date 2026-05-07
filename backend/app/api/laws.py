from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Law, LawMapping
from app.db.session import get_session_dep

router = APIRouter(prefix="/laws", tags=["laws"])


class LawOut(BaseModel):
    id: int
    identifier: str
    kind: str

    class Config:
        from_attributes = True


class MappingIn(BaseModel):
    obsolete_ref: str
    vigent_law_id: int
    notes: str | None = None


class MappingOut(MappingIn):
    id: int

    class Config:
        from_attributes = True


@router.get("", response_model=list[LawOut])
async def list_laws(db: AsyncSession = Depends(get_session_dep)):
    return (await db.execute(select(Law).order_by(Law.identifier))).scalars().all()


@router.post("", response_model=LawOut)
async def upload_law(
    identifier: str = Form(...),
    kind: str = Form("LC"),
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    db: AsyncSession = Depends(get_session_dep),
):
    if not file and not text:
        raise HTTPException(400, "either file or text is required")

    pdf_path: str | None = None
    if file:
        target = settings.laws_dir / f"{identifier.replace('/', '_')}_{file.filename}"
        target.write_bytes(await file.read())
        pdf_path = str(target)
        if file.content_type and "pdf" in file.content_type and not text:
            import fitz

            doc = fitz.open(target)
            try:
                text = "\n".join(page.get_text() for page in doc)
            finally:
                doc.close()

    law = Law(
        identifier=identifier, kind=kind, source_text=text or "", source_pdf_path=pdf_path
    )
    db.add(law)
    await db.flush()
    return law


@router.get("/mappings", response_model=list[MappingOut])
async def list_mappings(db: AsyncSession = Depends(get_session_dep)):
    return (await db.execute(select(LawMapping))).scalars().all()


@router.post("/mappings", response_model=MappingOut)
async def create_mapping(
    payload: MappingIn, db: AsyncSession = Depends(get_session_dep)
):
    m = LawMapping(**payload.model_dump())
    db.add(m)
    await db.flush()
    return m
