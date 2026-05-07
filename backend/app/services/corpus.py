"""Build the law corpus block consumed by the Claude prompt cache.

Centralizing this avoids drift between the detection-time classifier and the
proposal generator (both must hit the same cached prefix to get cache reads).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Law, LawMapping
from app.services.claude_client import build_law_corpus_block


async def build_corpus(db: AsyncSession) -> str:
    laws = (await db.execute(select(Law))).scalars().all()
    mappings = (await db.execute(select(LawMapping))).scalars().all()
    laws_payload = [
        {"identifier": law.identifier, "source_text": law.source_text}
        for law in laws
    ]
    law_by_id = {law.id: law.identifier for law in laws}
    mappings_payload: list[dict[str, str]] = [
        {
            "obsolete_ref": m.obsolete_ref,
            "vigent_ref": law_by_id.get(m.vigent_law_id, str(m.vigent_law_id)),
            "notes": m.notes or "",
        }
        for m in mappings
    ]
    return build_law_corpus_block(laws_payload, mappings_payload)


async def has_corpus(db: AsyncSession) -> bool:
    laws = (await db.execute(select(Law))).scalars().first()
    return laws is not None
