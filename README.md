# Atualizador do Livro — Reforma Tributária (PLP 108)

Aplicativo local para atualizar referências obsoletas a Projetos de Lei Complementar
(PLP 108, PLP 68, etc.) em livros jurídicos PDF, substituindo-as pelas Leis
Complementares vigentes da Reforma Tributária, preservando a diagramação original.

## Componentes

- **backend/** — FastAPI + PyMuPDF + SQLAlchemy + Anthropic SDK
- **frontend/** — React + Vite + TypeScript (UI lado-a-lado para revisão)
- **data/** — SQLite local, uploads, exports (gitignored)

## Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Acesse `http://localhost:5173`.

## Fluxo

1. **LawsLibrary** — cadastrar mappings (`PLP 108 → LC X/2025`) e fazer upload dos textos das leis vigentes.
2. **Upload** — enviar o PDF do livro.
3. **Review** — janela lado-a-lado: original (com highlights) × proposta da IA. Aceitar/rejeitar/editar trecho a trecho.
4. **HistoricalQueue** — fila separada para menções em contexto histórico (sempre exigem decisão manual).
5. **FigureReview** — figuras possivelmente desatualizadas; usuário aprova ou envia substituta.
6. **Verify** — checagem line-by-line garantindo que apenas trechos aprovados foram alterados.
7. **Export** — PDF (in-place) + DOCX + relatório de auditoria.
