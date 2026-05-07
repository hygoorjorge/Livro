import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../state/session";

export function Review() {
  const { sessionId } = useSession();
  const [mentions, setMentions] = useState<any[]>([]);
  const [active, setActive] = useState<any | null>(null);
  const [proposals, setProposals] = useState<any[]>([]);
  const [manualText, setManualText] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshMentions() {
    if (!sessionId) return;
    setMentions(await api.listMentions(sessionId));
  }

  useEffect(() => {
    refreshMentions();
  }, [sessionId]);

  async function selectMention(m: any) {
    setActive(m);
    setProposals(await api.proposalsForMention(m.id));
    setManualText("");
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
  }

  if (!sessionId) return <p>Selecione uma sessão na tela de Upload.</p>;

  return (
    <div>
      <h2>Revisão lado-a-lado</h2>
      <div className="split">
        <div className="pane">
          <h3>Menções detectadas</h3>
          <button onClick={refreshMentions}>Atualizar</button>
          <table>
            <thead>
              <tr>
                <th>Trecho</th>
                <th>Ref</th>
                <th>Hist?</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {mentions.map((m) => (
                <tr
                  key={m.id}
                  onClick={() => selectMention(m)}
                  style={{
                    cursor: "pointer",
                    background: active?.id === m.id ? "#fef3c7" : undefined,
                  }}
                >
                  <td>
                    <span className="mark">{m.raw_text}</span>
                  </td>
                  <td>{m.detected_ref}</td>
                  <td>{m.is_historical ? "sim" : "—"}</td>
                  <td>{m.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="pane">
          <h3>Proposta de atualização</h3>
          {!active && <p className="muted">Selecione uma menção ao lado.</p>}
          {active && (
            <>
              <p>
                <strong>Menção:</strong>{" "}
                <span className="mark">{active.raw_text}</span>{" "}
                <span className="muted">→ {active.detected_ref}</span>
              </p>
              {active.is_historical && (
                <p style={{ background: "#fee2e2", padding: 8, borderRadius: 6 }}>
                  ⚠ Menção em contexto histórico. Decida manualmente se mantém
                  ou atualiza.
                </p>
              )}
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
                  </div>
                  <div>
                    <strong>Original:</strong>
                    <pre style={{ whiteSpace: "pre-wrap", background: "#fef2f2", padding: 8 }}>
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
                <button onClick={manual}>Salvar como proposta manual aceita</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
