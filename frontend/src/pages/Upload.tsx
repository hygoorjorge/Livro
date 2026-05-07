import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../state/session";
import { ProgressBar } from "../components/ProgressBar";

export function Upload() {
  const { sessionId, setSessionId } = useSession();
  const [name, setName] = useState("Livro - Reforma Tributária");
  const [sessions, setSessions] = useState<any[]>([]);

  useEffect(() => {
    api.listSessions().then(setSessions);
  }, []);

  async function onUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    fd.set("name", name);
    const res = await api.uploadPdf(fd);
    setSessionId(res.session_id);
    setSessions(await api.listSessions());
  }

  const [useClassifier, setUseClassifier] = useState(true);
  async function startDetection() {
    if (!sessionId) return;
    const r = await api.detect(sessionId, useClassifier);
    alert(
      `Detecção iniciada em background. Classifier: ${r.classifier ? "ativo" : "desligado"}.`
    );
  }

  return (
    <div>
      <h2>Upload do livro</h2>
      <p className="muted">
        Faça upload do PDF do livro. O sistema fará o parse em background.
      </p>
      <form onSubmit={onUpload}>
        <div className="row">
          <input
            placeholder="Nome desta sessão"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="row">
          <input type="file" name="file" accept="application/pdf" required />
          <button className="primary" type="submit">
            Enviar
          </button>
        </div>
      </form>

      <h3>Sessões</h3>
      <table>
        <thead>
          <tr>
            <th></th>
            <th>ID</th>
            <th>Nome</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.id}>
              <td>
                <input
                  type="radio"
                  checked={sessionId === s.id}
                  onChange={() => setSessionId(s.id)}
                />
              </td>
              <td>{s.id}</td>
              <td>{s.name}</td>
              <td>{s.status}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ marginTop: 16 }}>
        <label className="row" style={{ marginBottom: 8 }}>
          <input
            type="checkbox"
            checked={useClassifier}
            onChange={(e) => setUseClassifier(e.target.checked)}
            style={{ width: "auto" }}
          />
          <span className="muted">
            Filtrar candidatos via Claude (recomendado — exige leis cadastradas)
          </span>
        </label>
        <button onClick={startDetection} disabled={!sessionId} className="primary">
          Iniciar detecção de menções
        </button>
      </div>
      <ProgressBar sessionId={sessionId} />
    </div>
  );
}
