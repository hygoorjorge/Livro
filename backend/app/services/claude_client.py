"""Anthropic Claude API client wrapper with prompt caching.

Caching strategy: the system prompt + uploaded law texts + obsolete-to-vigent
mapping form a stable prefix that is reused across hundreds of calls per book.
That prefix carries the ``cache_control`` breakpoint; the per-paragraph payload
is appended after the breakpoint and stays uncached.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


SYSTEM_PROMPT = (
    "Você é especialista em Direito Tributário brasileiro, com domínio "
    "completo da Reforma Tributária instituída pela EC 132/2023 e suas "
    "Leis Complementares regulamentadoras. Sua tarefa é atualizar referências "
    "obsoletas a Projetos de Lei Complementar (PLP) pelas normas vigentes "
    "correspondentes, preservando rigorosamente o estilo do autor, a estrutura "
    "argumentativa e a precisão técnica do texto original.\n\n"
    "Regras invioláveis:\n"
    "1. Nunca altere conteúdo fora do trecho indicado.\n"
    "2. Nunca altere citações textuais (entre aspas ou em bloco) que reproduzam "
    "literalmente o PLP — são citação histórica.\n"
    "3. Quando houver ambiguidade jurídica (veto parcial, dispositivo migrado "
    "para LC distinta, etc.), sinalize via needs_human_check em vez de inferir.\n"
    "4. Quando o autor menciona o PLP em contexto histórico/de tramitação, "
    "marque is_historical_context=true e não proponha alteração."
)


PROPOSAL_TOOL = {
    "name": "submit_proposal",
    "description": (
        "Submeta a proposta de atualização do trecho. Use confidence baixa "
        "(<0.6) e needs_human_check=true em casos de ambiguidade."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "original_excerpt": {
                "type": "string",
                "description": "Trecho original exato do livro a ser substituído.",
            },
            "proposed_excerpt": {
                "type": "string",
                "description": "Trecho atualizado proposto.",
            },
            "changed_segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "orig": {"type": "string"},
                        "new": {"type": "string"},
                        "article_ref": {"type": "string"},
                    },
                    "required": ["orig", "new"],
                },
                "description": "Lista de substituições pontuais aplicadas.",
            },
            "justification": {
                "type": "string",
                "description": "Justificativa jurídica curta (1-3 frases).",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confiança na proposta (0 a 1).",
            },
            "needs_human_check": {
                "type": "boolean",
                "description": "True se há ambiguidade que exige revisão humana.",
            },
            "is_historical_context": {
                "type": "boolean",
                "description": "True se a menção é em contexto histórico (não atualizar).",
            },
        },
        "required": [
            "original_excerpt",
            "proposed_excerpt",
            "changed_segments",
            "justification",
            "confidence",
            "needs_human_check",
            "is_historical_context",
        ],
    },
}


CLASSIFIER_TOOL = {
    "name": "submit_classifications",
    "description": "Classifique cada candidato a menção legislativa.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "integer"},
                        "is_mention": {"type": "boolean"},
                        "normalized_ref": {"type": "string"},
                        "is_historical": {"type": "boolean"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "rationale": {"type": "string"},
                    },
                    "required": ["candidate_id", "is_mention", "confidence"],
                },
            }
        },
        "required": ["results"],
    },
}


@dataclass
class ProposalResult:
    original_excerpt: str
    proposed_excerpt: str
    changed_segments: list[dict[str, str]]
    justification: str
    confidence: float
    needs_human_check: bool
    is_historical_context: bool
    cache_hit: bool
    model: str


@dataclass
class ClassificationResult:
    candidate_id: int
    is_mention: bool
    normalized_ref: str | None
    is_historical: bool
    confidence: float
    rationale: str | None


def build_law_corpus_block(laws: list[dict[str, str]], mappings: list[dict[str, str]]) -> str:
    """Build the cacheable corpus block from uploaded laws + mapping table."""
    parts: list[str] = ["## Mapeamento de PLPs convertidos\n"]
    for m in mappings:
        notes = f" (notas: {m['notes']})" if m.get("notes") else ""
        parts.append(f"- {m['obsolete_ref']} → {m['vigent_ref']}{notes}")
    parts.append("\n## Textos integrais das leis vigentes\n")
    for law in laws:
        parts.append(f"### {law['identifier']}\n")
        parts.append(law["source_text"])
        parts.append("\n---\n")
    return "\n".join(parts)


class ClaudeClient:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY não configurada. Defina no .env ou env var."
            )
        self.client = AsyncAnthropic(api_key=key)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_claude_calls)

    def _cached_system(self, law_corpus_block: str) -> list[dict[str, Any]]:
        return [
            {"type": "text", "text": SYSTEM_PROMPT},
            {
                "type": "text",
                "text": law_corpus_block,
                "cache_control": {"type": "ephemeral"},
            },
        ]

    async def propose_update(
        self,
        *,
        law_corpus_block: str,
        paragraph_text: str,
        mention_raw: str,
        mention_ref: str,
        neighbor_paragraphs: list[str] | None = None,
        model: str | None = None,
    ) -> ProposalResult:
        model = model or settings.proposal_model
        neighbor = "\n\n".join(neighbor_paragraphs or [])
        user_text = (
            f"Parágrafo-alvo:\n\"\"\"\n{paragraph_text}\n\"\"\"\n\n"
            f"Menção detectada: '{mention_raw}' (referência normalizada: {mention_ref}).\n\n"
            f"Contexto vizinho:\n\"\"\"\n{neighbor}\n\"\"\"\n\n"
            "Proponha a atualização chamando a ferramenta submit_proposal."
        )
        async with self._semaphore:
            response = await self.client.messages.create(
                model=model,
                max_tokens=4096,
                system=self._cached_system(law_corpus_block),
                tools=[PROPOSAL_TOOL],
                tool_choice={"type": "tool", "name": "submit_proposal"},
                messages=[{"role": "user", "content": user_text}],
            )

        tool_use = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_use is None:
            raise RuntimeError("Claude não retornou tool_use submit_proposal")
        data = tool_use.input
        cache_hit = (response.usage.cache_read_input_tokens or 0) > 0
        logger.info(
            "proposal model=%s cache_read=%d cache_create=%d input=%d output=%d",
            model,
            response.usage.cache_read_input_tokens or 0,
            response.usage.cache_creation_input_tokens or 0,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return ProposalResult(
            original_excerpt=data["original_excerpt"],
            proposed_excerpt=data["proposed_excerpt"],
            changed_segments=data["changed_segments"],
            justification=data["justification"],
            confidence=float(data["confidence"]),
            needs_human_check=bool(data["needs_human_check"]),
            is_historical_context=bool(data["is_historical_context"]),
            cache_hit=cache_hit,
            model=model,
        )

    async def classify_candidates(
        self,
        *,
        law_corpus_block: str,
        candidates: list[dict[str, Any]],
        model: str | None = None,
    ) -> list[ClassificationResult]:
        model = model or settings.classifier_model
        payload = json.dumps(candidates, ensure_ascii=False, indent=2)
        user_text = (
            "Classifique os candidatos a menção legislativa abaixo. Para cada "
            "candidato, decida se é realmente uma menção a um PLP/PL/PEC/MPV "
            "(is_mention), se está em contexto histórico (is_historical) e "
            "normalize a referência. Responda chamando submit_classifications.\n\n"
            f"Candidatos (JSON):\n{payload}"
        )
        async with self._semaphore:
            response = await self.client.messages.create(
                model=model,
                max_tokens=4096,
                system=self._cached_system(law_corpus_block),
                tools=[CLASSIFIER_TOOL],
                tool_choice={"type": "tool", "name": "submit_classifications"},
                messages=[{"role": "user", "content": user_text}],
            )
        tool_use = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_use is None:
            raise RuntimeError("Claude não retornou tool_use submit_classifications")
        results = tool_use.input.get("results", [])
        return [
            ClassificationResult(
                candidate_id=int(r["candidate_id"]),
                is_mention=bool(r["is_mention"]),
                normalized_ref=r.get("normalized_ref"),
                is_historical=bool(r.get("is_historical", False)),
                confidence=float(r["confidence"]),
                rationale=r.get("rationale"),
            )
            for r in results
        ]
