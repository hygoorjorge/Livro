import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../state/session";
import { Highlight, PdfPane, PdfPaneHandle } from "../components/PdfPane";
import { ProgressBar } from "../components/ProgressBar";

export function Review() {
  const { sessionId } = useSession();
  const [mentions, setMentions] = useState<any[]>([]);
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [active, setActive] = useState<any | null>(null);
  const [proposals, setProposals] = useState<any[]>([]);
  const [manualText, setManualText] = useState("");
  const [busy, setBusy] = useState(false);
  const pdfRef = useRef<PdfPaneHandle>(null);

  async function refreshMentions() {
    if (!sessionId) return;
    const list = await api.listMentions(sessionId);
    const nonHistorical = list.filter(
      (m) => !m.is_historical || m.status === "confirmed"
    );
    setMentions(nonHistorical);
    setHighlights(await api.listHighlights(sessionId));
  }

  useEffect(() => {
    refreshMentions();
  }, [sessionId]);

  async function selectMention(m: any) {
    setActive(m);
    setProposals(await api.proposalsForMention(m.id));
    setManualText("");
    pdfRef.current?.scrollToMention(m.id);
  }

  async function genAuto() {
    if (!active) return;
    setBusy(true);
    try {
      await api.generateAuto(active.id);
      setProposals(await api.proposalsForMention(active.id));
    } finally {
      setBusy(false);
    }
  }

  async function accept(p: any, edited?: string) {
    await api.acceptProposal(p.id, edited);
    setProposals(await api.proposalsForMention(active.id));
    await refreshMentions();
  }

  async function reject(p: any) {
    await api.rejectProposal(p.id);
    setProposals(await api.proposalsForMention(active.id));
  }

  async function manual() {
    if (!active || !manualText.trim()) return;
    await api.generateManual(active.id, manualText.trim());
    setProposals(await api.proposalsForMention(active.id));
    setManualText("");
    await refreshMentions();
  }

  if (!sessionId) return <p>Selecione uma sessão na tela de Upload.</p>;

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Revisão lado-a-lado</h2>
        <div className="row">
          <button onClick={refreshMentions}>↻ Atualizar</button>
          <button
            onClick={async () => {
              await api.batchGenerate(sessionId);
              alert(
                "Geração em lote iniciada — acompanhe na barra de progresso. Atualize a tela para ver as propostas conforme aparecem."
              );
            }}
          >
            ⚡ Gerar todas as propostas pendentes
          </button>
          <a href="/historical">Fila histórica →</a>
        </div>
      </div>
      <ProgressBar sessionId={sessionId} />
      <div className="split">
        <div className="pane" style={{ padding: 0 }}>
          <PdfPane
            ref={pdfRef}
            url={`/api/pdf/${sessionId}/source`}
            highlights={highlights}
            activeMentionId={active?.id ?? null}
            onHighlightClick={(id) => {
              const m = mentions.find((mm) => mm.id === id);
              if (m) selectMention(m);
            }}
          />
        </div>

        <div className="pane">
          <h3 style={{ marginTop: 0 }}>
            Proposta de atualização
            <span className="muted" style={{ marginLeft: 8 }}>
              ({mentions.length} menções não-históricas pendentes)
            </span>
          </h3>

          {!active && (
            <>
              <p className="muted">
                Clique em uma menção destacada no PDF (ou na lista abaixo) para
                editar.
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Trecho</th>
                    <th>Ref</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {mentions.map((m) => (
                    <tr
                      key={m.id}
                      onClick={() => selectMention(m)}
                      style={{ cursor: "pointer" }}
                    >
                      <td>
                        <span className="mark">{m.raw_text}</span>
                      </td>
                      <td>{m.detected_ref}</td>
                      <td>{m.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {active && (
            <>
              <p>
                <strong>Menção:</strong>{" "}
                <span className="mark">{active.raw_text}</span>{" "}
                <span className="muted">→ {active.detected_ref}</span>{" "}
                <button onClick={() => setActive(null)} style={{ marginLeft: 8 }}>
                  voltar
                </button>
              </p>
              <div className="row">
                <button onClick={genAuto} disabled={busy} className="primary">
                  {busy ? "Gerando..." : "Gerar proposta automática (Claude)"}
                </button>
              </div>

              {proposals.map((p) => (
                <div
                  key={p.id}
                  style={{
                    border: "1px solid #d1d5db",
                    borderRadius: 8,
                    padding: 12,
                    marginTop: 12,
                  }}
                >
                  <div className="muted">
                    {p.mode} · {p.status} · conf {p.confidence?.toFixed?.(2)} ·
                    cache {p.prompt_cache_hit ? "✔" : "—"}
                    {p.needs_human_check && (
                      <span className="badge danger" style={{ marginLeft: 8 }}>
                        revisão humana
                      </span>
                    )}
                  </div>
                  <div>
                    <strong>Original:</strong>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        background: "#fef2f2",
                        padding: 8,
                      }}
                    >
                      {p.original_text}
                    </pre>
                  </div>
                  <div>
                    <strong>Proposto:</strong>
                    <textarea
                      defaultValue={p.proposed_text}
                      rows={4}
                      onBlur={(e) => (p.proposed_text = e.target.value)}
                    />
                  </div>
                  {p.justification && (
                    <p className="muted">
                      <strong>Justificativa:</strong> {p.justification}
                    </p>
                  )}
                  {p.status === "pending" && (
                    <div className="row">
                      <button
                        className="primary"
                        onClick={() => accept(p, p.proposed_text)}
                      >
                        Aceitar
                      </button>
                      <button className="danger" onClick={() => reject(p)}>
                        Rejeitar
                      </button>
                    </div>
                  )}
                </div>
              ))}

              <div style={{ marginTop: 16 }}>
                <h4>Edição manual</h4>
                <textarea
                  rows={4}
                  value={manualText}
                  onChange={(e) => setManualText(e.target.value)}
                  placeholder="Digite o texto final manualmente"
                />
                <button onClick={manual}>
                  Salvar como proposta manual aceita
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
