import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../state/session";

export function HistoricalQueue() {
  const { sessionId } = useSession();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const all = await api.listMentions(sessionId);
      setItems(
        all.filter(
          (m) =>
            m.is_historical &&
            (m.status === "awaiting_user_decision" || m.status === "pending")
        )
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [sessionId]);

  async function decide(mentionId: number, status: "confirmed" | "dismissed") {
    await api.setMentionStatus(mentionId, status);
    await refresh();
  }

  if (!sessionId) return <p>Selecione uma sessão.</p>;

  return (
    <div>
      <h2>Fila de menções históricas</h2>
      <p className="muted">
        Estas menções aparecem em contexto de tramitação ou análise histórica
        (ex.: "durante a tramitação do PLP 108"). Você optou por decidir
        manualmente cada uma. Confirmar manda para a fila normal de
        atualização; dispensar mantém o texto original intacto.
      </p>
      <button onClick={refresh} disabled={loading}>
        {loading ? "Carregando..." : "↻ Atualizar"}
      </button>
      {items.length === 0 && (
        <p className="muted" style={{ marginTop: 16 }}>
          Sem pendências históricas.
        </p>
      )}
      <table style={{ marginTop: 16 }}>
        <thead>
          <tr>
            <th>Menção</th>
            <th>Referência</th>
            <th>Parágrafo</th>
            <th>Ação</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.id}>
              <td>
                <span className="mark">{m.raw_text}</span>
              </td>
              <td>{m.detected_ref}</td>
              <td className="muted">{m.paragraph_id}</td>
              <td>
                <div className="row">
                  <button
                    className="primary"
                    onClick={() => decide(m.id, "confirmed")}
                    title="Tratar como menção atualizável"
                  >
                    Atualizar
                  </button>
                  <button
                    onClick={() => decide(m.id, "dismissed")}
                    title="Manter texto original (preservar histórico)"
                  >
                    Manter histórico
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
