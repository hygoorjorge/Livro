"""Detect mentions of obsolete legislative projects (PLP, PL, PEC, MPV).

Two-layer approach:
  1. High-recall regex over normalized paragraph text.
  2. Claude classifier (in batch) confirms each candidate, marks historical
     context, and normalizes the reference (e.g. "P.L.P. 108" -> "PLP 108").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PROJECT_PATTERNS = [
    re.compile(
        r"\b(?:P\.?\s*L\.?\s*P\.?|Projeto\s+de\s+Lei\s+Complementar)"
        r"\s*(?:n[º°ºo]?\.?\s*)?(\d{1,5})(?:\s*/\s*(\d{2,4}))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:P\.?\s*L\.?|Projeto\s+de\s+Lei)"
        r"\s*(?:n[º°ºo]?\.?\s*)?(\d{1,5})(?:\s*/\s*(\d{2,4}))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bPEC\s*(?:n[º°ºo]?\.?\s*)?(\d{1,5})(?:\s*/\s*(\d{2,4}))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bMPV?\s*(?:n[º°ºo]?\.?\s*)?(\d{1,5})(?:\s*/\s*(\d{2,4}))?",
        re.IGNORECASE,
    ),
]

REFORM_KEYWORDS = re.compile(
    r"\b(reforma\s+tribut[áa]ria|IBS|CBS|Imposto\s+Seletivo|Comit[êe]\s+Gestor)\b",
    re.IGNORECASE,
)

HISTORICAL_HINTS = re.compile(
    r"\b(durante\s+a\s+tramita[cç][ãa]o|na\s+vers[ãa]o\s+original|"
    r"projeto\s+original|antes\s+da\s+convers[ãa]o|"
    r"em\s+sua\s+reda[cç][ãa]o\s+inicial|na\s+época|"
    r"à\s+época|hist[óo]ric[ao])\b",
    re.IGNORECASE,
)


def _kind_for_pattern(idx: int) -> str:
    return ["PLP", "PL", "PEC", "MPV"][idx]


def _normalize(kind: str, num: str, year: str | None) -> str:
    if year:
        if len(year) == 2:
            year = ("20" if int(year) < 50 else "19") + year
        return f"{kind} {int(num)}/{year}"
    return f"{kind} {int(num)}"


@dataclass
class CandidateMention:
    char_start: int
    char_end: int
    raw_text: str
    detected_ref: str
    has_reform_keyword_nearby: bool
    has_historical_hint_nearby: bool


def find_candidates(paragraph_text: str, mappings: dict[str, int] | None = None) -> list[CandidateMention]:
    """Return regex candidates within a single paragraph.

    ``mappings`` is the user's obsolete-ref -> law_id map. If provided, mentions
    not in the map are still returned (so the user can decide), but ones in the
    map get higher implicit priority downstream.
    """
    out: list[CandidateMention] = []
    for p_idx, pattern in enumerate(PROJECT_PATTERNS):
        kind = _kind_for_pattern(p_idx)
        for m in pattern.finditer(paragraph_text):
            num = m.group(1)
            year = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            ref = _normalize(kind, num, year)

            window_start = max(0, m.start() - 240)
            window_end = min(len(paragraph_text), m.end() + 240)
            window = paragraph_text[window_start:window_end]

            out.append(
                CandidateMention(
                    char_start=m.start(),
                    char_end=m.end(),
                    raw_text=m.group(0),
                    detected_ref=ref,
                    has_reform_keyword_nearby=bool(REFORM_KEYWORDS.search(window)),
                    has_historical_hint_nearby=bool(HISTORICAL_HINTS.search(window)),
                )
            )
    out.sort(key=lambda c: c.char_start)
    return _dedupe(out)


def _dedupe(items: list[CandidateMention]) -> list[CandidateMention]:
    """Remove overlapping matches keeping the longest/most specific (PLP over PL)."""
    items.sort(key=lambda c: (c.char_start, -(c.char_end - c.char_start)))
    kept: list[CandidateMention] = []
    for cand in items:
        if kept and cand.char_start < kept[-1].char_end:
            continue
        kept.append(cand)
    return kept


def context_window(paragraph_text: str, mention: CandidateMention, radius: int = 320) -> str:
    s = max(0, mention.char_start - radius)
    e = min(len(paragraph_text), mention.char_end + radius)
    prefix = "..." if s > 0 else ""
    suffix = "..." if e < len(paragraph_text) else ""
    return f"{prefix}{paragraph_text[s:e]}{suffix}"
