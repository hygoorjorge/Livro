"""Generate a formatted PDF audit report using PyMuPDF."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

_A4_W = 595.0
_A4_H = 842.0
_MARGIN = 50.0
_CONTENT_W = _A4_W - _MARGIN * 2
_FONT = "helv"
_FONT_B = "hebo"

_C_DARK = (0.1, 0.1, 0.1)
_C_MUTED = (0.45, 0.45, 0.45)
_C_BLUE = (0.15, 0.25, 0.65)
_C_GREEN = (0.05, 0.45, 0.15)
_C_RED = (0.65, 0.05, 0.05)
_C_RULE = (0.78, 0.78, 0.78)


class _Writer:
    """Cursor-based writer that auto-paginates on overflow."""

    def __init__(self) -> None:
        self.doc = fitz.open()
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=_A4_W, height=_A4_H)
        self.y = _MARGIN
        pnum = len(self.doc)
        self.page.insert_text(
            (_A4_W - _MARGIN, _A4_H - 22),
            str(pnum),
            fontname=_FONT,
            fontsize=8,
            color=_C_MUTED,
        )

    def _ensure(self, needed: float) -> None:
        if self.y + needed > _A4_H - _MARGIN:
            self._new_page()

    def skip(self, pts: float = 8.0) -> None:
        self.y += pts

    def rule(self, color: tuple = _C_RULE, weight: float = 0.5) -> None:
        self._ensure(8)
        self.page.draw_line(
            (_MARGIN, self.y), (_A4_W - _MARGIN, self.y),
            color=color, width=weight,
        )
        self.y += 6

    def _insert(
        self,
        text: str,
        fontsize: float,
        bold: bool,
        color: tuple,
        indent: float,
        max_lines: int,
    ) -> None:
        fn = _FONT_B if bold else _FONT
        x0 = _MARGIN + indent
        w = _CONTENT_W - indent
        # Conservative chars-per-line estimate (0.55 × fontsize per char average)
        cpl = max(1, int(w / (fontsize * 0.55)))
        lines = max(1, min(max_lines, (len(text) + cpl - 1) // cpl))
        h = lines * fontsize * 1.45 + 2
        self._ensure(h)
        rect = fitz.Rect(x0, self.y, x0 + w, self.y + h)
        overflow = self.page.insert_textbox(
            rect, text, fontname=fn, fontsize=fontsize, color=color,
        )
        if overflow < 0 and max_lines < 20:
            # Text did not fit — expand and retry on same or next page
            self._insert(text, fontsize, bold, color, indent, max_lines + 4)
            return
        self.y += h

    def h1(self, text: str) -> None:
        self._ensure(36)
        self._insert(text, 20, bold=True, color=_C_DARK, indent=0, max_lines=2)
        self.skip(4)

    def h2(self, text: str) -> None:
        self.skip(6)
        self.rule(color=(0.6, 0.6, 0.8), weight=0.8)
        self._insert(text, 13, bold=True, color=_C_BLUE, indent=0, max_lines=2)
        self.skip(2)

    def h3(self, text: str, color: tuple = _C_DARK) -> None:
        self._ensure(20)
        self._insert(text, 11, bold=True, color=color, indent=0, max_lines=2)

    def text(
        self,
        text: str,
        fontsize: float = 9.5,
        bold: bool = False,
        color: tuple = _C_DARK,
        indent: float = 0,
        max_lines: int = 6,
    ) -> None:
        self._insert(text, fontsize, bold, color, indent, max_lines)

    def kv(self, key: str, value: str, indent: float = 0) -> None:
        """Key: value pair on the same baseline (key bold, value normal)."""
        self._ensure(14)
        fn_k = _FONT_B
        fn_v = _FONT
        fs = 9.5
        x0 = _MARGIN + indent
        # Key portion
        key_w = len(key) * fs * 0.62
        self.page.insert_text((x0, self.y + fs), key, fontname=fn_k, fontsize=fs, color=_C_DARK)
        # Value portion
        self.page.insert_text(
            (x0 + key_w + 4, self.y + fs), value, fontname=fn_v, fontsize=fs, color=_C_MUTED,
        )
        self.y += fs * 1.6

    def label_box(self, label: str, color: tuple) -> None:
        """Small colored rectangle with a status label."""
        self._ensure(16)
        fs = 8.5
        pad = 3
        w = len(label) * fs * 0.58 + pad * 2
        rect = fitz.Rect(_MARGIN, self.y, _MARGIN + w, self.y + fs + pad * 2)
        self.page.draw_rect(rect, color=color, fill=(*color[:3], 0.12), width=0.6)
        self.page.insert_text(
            (_MARGIN + pad, self.y + fs + pad - 1), label,
            fontname=_FONT_B, fontsize=fs, color=color,
        )
        self.y += fs + pad * 2 + 2

    def save(self, path: Path) -> None:
        self.doc.save(str(path), garbage=4, deflate=True)
        self.doc.close()


def _status_color(status: str) -> tuple:
    if status in ("accepted", "edited"):
        return _C_GREEN
    if status == "rejected":
        return _C_RED
    return _C_MUTED


def _truncate(text: str, limit: int = 400) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [{len(text) - limit} chars omitted]"


def export_audit_pdf(audit: dict[str, Any], output_path: Path) -> Path:
    """Render *audit* (from _collect_audit) as a formatted PDF at *output_path*."""
    w = _Writer()
    s = audit["session"]
    proposals: list[dict] = audit["proposals"]
    changelog: list[dict] = audit["change_log"]
    runs: list[dict] = audit["verification_runs"]

    # ── Cover ──────────────────────────────────────────────────────────────────
    w.skip(60)
    w.h1("Relatório de Auditoria")
    w.skip(4)
    w.text(
        f"Sessão #{s['id']} — {s['name']}",
        fontsize=12, color=_C_MUTED,
    )
    w.skip(20)
    w.rule()
    w.skip(4)
    w.kv("Status:", s["status"])
    w.kv("Criado em:", s["created_at"])
    w.kv("Atualizado em:", s["updated_at"])
    w.skip(8)
    w.text("Integridade do documento", bold=True, fontsize=9.5)
    w.kv("  Hash original (SHA-256):", s["hash_original"] or "—")
    w.kv("  Hash final    (SHA-256):", s["hash_final"] or "—")
    w.skip(8)
    w.text(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} pelo Livro Updater.",
        fontsize=8.5, color=_C_MUTED,
    )

    # ── Proposals ──────────────────────────────────────────────────────────────
    w.h2(f"Propostas ({len(proposals)})")

    accepted = [p for p in proposals if p["status"] in ("accepted", "edited")]
    rejected = [p for p in proposals if p["status"] == "rejected"]
    pending_p = [p for p in proposals if p["status"] == "pending"]

    w.kv("Aceitas / editadas:", str(len(accepted)))
    w.kv("Rejeitadas:", str(len(rejected)))
    w.kv("Pendentes:", str(len(pending_p)))
    w.skip(6)

    for p in proposals:
        w.rule(color=(0.88, 0.88, 0.88), weight=0.4)
        sc = _status_color(p["status"])
        w.h3(f"Proposta #{p['id']}  [{p['status'].upper()}]  ({p['mode']})", color=sc)
        model_info = p.get("claude_model") or "—"
        cache = "sim" if p.get("prompt_cache_hit") else "não"
        conf = p.get("confidence", 0)
        w.text(
            f"Modelo: {model_info}  |  cache: {cache}  |  confiança: {conf:.0%}  |  revisão humana: {'sim' if p.get('needs_human_check') else 'não'}",
            fontsize=8.5, color=_C_MUTED,
        )
        w.skip(3)
        w.text("Original:", bold=True, fontsize=8.5)
        w.text(_truncate(p.get("original") or "—"), fontsize=8.5, indent=12, color=(0.3, 0.1, 0.1))
        w.text("Proposto:", bold=True, fontsize=8.5)
        w.text(_truncate(p.get("proposed") or "—"), fontsize=8.5, indent=12, color=(0.1, 0.3, 0.1))
        if p.get("justification"):
            w.text("Justificativa:", bold=True, fontsize=8.5)
            w.text(_truncate(p["justification"], 300), fontsize=8.5, indent=12, color=_C_MUTED)
        w.skip(4)

    # ── Verification runs ──────────────────────────────────────────────────────
    w.h2(f"Verificações ({len(runs)})")

    if not runs:
        w.text("Nenhuma verificação executada.", color=_C_MUTED)
    for r in runs:
        passed = r["passed"]
        label = "PASSOU" if passed else "FALHOU"
        color = _C_GREEN if passed else _C_RED
        w.label_box(label, color)
        w.kv("  Data/hora:", r["ts"])
        w.kv("  Diffs totais:", str(r["total_diffs"]))
        unauth = r.get("unauthorized_diffs") or []
        w.kv("  Diffs não autorizados:", str(len(unauth)))
        for u in unauth:
            w.skip(2)
            w.text(
                f"  ✗ pág. {u.get('page_num')} — parágrafo {u.get('paragraph_index')}",
                fontsize=8.5, color=_C_RED,
            )
            for diff_line in (u.get("diff") or [])[:8]:
                w.text(f"     {diff_line}", fontsize=7.5, color=_C_MUTED, max_lines=2)
        w.skip(6)

    # ── Change log ─────────────────────────────────────────────────────────────
    w.h2(f"Histórico de decisões ({len(changelog)})")

    if not changelog:
        w.text("Nenhum registro no histórico.", color=_C_MUTED)
    for entry in changelog:
        w.text(
            f"[{entry['ts'][:19]}]  {entry['kind']}  ref={entry['ref_id']}  actor={entry['actor']}",
            fontsize=8.5,
        )
        if entry.get("before") or entry.get("after"):
            w.text(
                f"  {entry.get('before') or '—'}  →  {entry.get('after') or '—'}",
                fontsize=8.0, color=_C_MUTED, indent=10,
            )

    w.save(output_path)
    return output_path
