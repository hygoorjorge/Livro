import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../state/session";

export function FigureReview() {
  const { sessionId } = useSession();
  const [figures, setFigures] = useState<any[]>([]);

  async function refresh() {
    if (!sessionId) return;
    setFigures(await api.listFigures(sessionId));
  }

  useEffect(() => {
    refresh();
  }, [sessionId]);

  async function scan() {
    if (!sessionId) return;
    const r = await api.scanFigures(sessionId);
    alert(`${r.flagged} figuras sinalizadas como possivelmente desatualizadas.`);
    await refresh();
  }

  async function keep(id: number) {
    await api.keepFigure(id);
    await refresh();
  }

  async function replace(id: number, file: File) {
    await api.replaceFigure(id, file);
    await refresh();
  }

  if (!sessionId) return <p>Selecione uma sessão.</p>;

  return (
    <div>
      <h2>Revisão de figuras</h2>
      <div className="row">
        <button onClick={scan} className="primary">
          Detectar figuras suspeitas
        </button>
        <button onClick={refresh}>Atualizar</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Legenda</th>
            <th>Motivo</th>
            <th>Status</th>
            <th>Ação</th>
          </tr>
        </thead>
        <tbody>
          {figures.map((f) => (
            <tr key={f.id}>
              <td>{f.id}</td>
              <td>{f.caption_text || <span className="muted">—</span>}</td>
              <td>{f.suspicion_reason || <span className="muted">—</span>}</td>
              <td>{f.status}</td>
              <td>
                <div className="row">
                  <button onClick={() => keep(f.id)}>Manter</button>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) =>
                      e.target.files?.[0] && replace(f.id, e.target.files[0])
                    }
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
