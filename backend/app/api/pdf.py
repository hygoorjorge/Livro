from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Page, Paragraph, Session, SessionStatus, TextSpan, Figure
from app.db.session import SessionLocal, get_session_dep
from app.services.pdf_parser import file_sha256, parse_pdf

router = APIRouter(prefix="/pdf", tags=["pdf"])


async def _ingest_pdf(session_id: int, pdf_path: str) -> None:
    parsed_pages = parse_pdf(pdf_path)
    async with SessionLocal() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return
        session.status = SessionStatus.parsing.value
        for parsed in parsed_pages:
            page = Page(
                session_id=session_id,
                page_num=parsed.page_num,
                width=parsed.width,
                height=parsed.height,
            )
            db.add(page)
            await db.flush()
            span_id_by_index: dict[int, int] = {}
            for span in parsed.spans:
                row = TextSpan(
                    page_id=page.id,
                    span_index=span.span_index,
                    text=span.text,
                    bbox_x0=span.bbox[0],
                    bbox_y0=span.bbox[1],
                    bbox_x1=span.bbox[2],
                    bbox_y1=span.bbox[3],
                    font_name=span.font_name,
                    font_size=span.font_size,
                    color=span.color,
                    flags=span.flags,
                )
                db.add(row)
                await db.flush()
                span_id_by_index[span.span_index] = row.id
            for para in parsed.paragraphs:
                db.add(
                    Paragraph(
                        page_id=page.id,
                        paragraph_index=para.paragraph_index,
                        span_ids_json=para.span_indices,
                        full_text=para.full_text,
                        kind=para.kind.value,
                        protected=para.kind.value == "block_quote",
                    )
                )
            for fig in parsed.figures:
                db.add(
                    Figure(
                        page_id=page.id,
                        bbox_x0=fig.bbox[0],
                        bbox_y0=fig.bbox[1],
                        bbox_x1=fig.bbox[2],
                        bbox_y1=fig.bbox[3],
                        image_hash=fig.image_hash,
                        caption_text=fig.caption_text,
                    )
                )
        session.status = SessionStatus.detecting.value
        await db.commit()


@router.post("/upload")
async def upload_pdf(
    background: BackgroundTasks,
    name: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session_dep),
):
    target = settings.uploads_dir / file.filename
    target.write_bytes(await file.read())
    digest = file_sha256(target)

    session = Session(
        name=name,
        pdf_path=str(target),
        status=SessionStatus.created.value,
        hash_original=digest,
    )
    db.add(session)
    await db.flush()
    sid = session.id

    background.add_task(_ingest_pdf, sid, str(target))
    return {"session_id": sid, "status": session.status}


@router.get("/{session_id}/source")
async def download_source(session_id: int, db: AsyncSession = Depends(get_session_dep)):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    return FileResponse(session.pdf_path, media_type="application/pdf")


@router.get("/{session_id}/export.pdf")
async def download_export_pdf(session_id: int):
    path = settings.exports_dir / f"session_{session_id}.pdf"
    if not path.exists():
        raise HTTPException(404, "export not generated yet")
    return FileResponse(path, media_type="application/pdf")


@router.get("/{session_id}/export.docx")
async def download_export_docx(session_id: int):
    path = settings.exports_dir / f"session_{session_id}.docx"
    if not path.exists():
        raise HTTPException(404, "export not generated yet")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
