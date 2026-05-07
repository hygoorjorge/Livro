import { useState } from "react";
import { api } from "../api/client";
import { useSession } from "../state/session";

export function Verify() {
  const { sessionId } = useSession();
  const [exporting, setExporting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function exportNow() {
    if (!sessionId) return;
    setExporting(true);
    setErr(null);
    try {
      const r = await api.exportSession(sessionId);
      setResult({ kind: "export", ...r });
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setExporting(false);
    }
  }

  async function verifyNow() {
    if (!sessionId) return;
    setVerifying(true);
    setErr(null);
    try {
      const r = await api.runVerification(sessionId);
      setResult({ kind: "verify", ...r });
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setVerifying(false);
    }
  }

  if (!sessionId) return <p>Selecione uma sessão.</p>;

  return (
    <div>
      <h2>Verificação & Exportação</h2>
      <p className="muted">
        1. Exporte para gerar PDF e DOCX. 2. Rode a verificação line-by-line
        para garantir que apenas trechos aprovados foram alterados.
      </p>
      <div className="row">
        <button onClick={exportNow} disabled={exporting} className="primary">
          {exporting ? "Exportando..." : "Exportar PDF + DOCX"}
        </button>
        <button onClick={verifyNow} disabled={verifying}>
          {verifying ? "Verificando..." : "Rodar verificação final"}
        </button>
        <a href={`/api/pdf/${sessionId}/export.pdf`} target="_blank">
          Baixar PDF
        </a>
        <a href={`/api/pdf/${sessionId}/export.docx`} target="_blank">
          Baixar DOCX
        </a>
        <a href={`/api/verify/${sessionId}/audit.pdf`} target="_blank">
          Baixar auditoria (PDF)
        </a>
        <a href={`/api/verify/${sessionId}/audit.md`} target="_blank">
          Baixar auditoria (Markdown)
        </a>
        <a href={`/api/verify/${sessionId}/audit.json`} target="_blank">
          Auditoria (JSON)
        </a>
      </div>
      {err && (
        <pre style={{ background: "#fee2e2", padding: 12, borderRadius: 6 }}>{err}</pre>
      )}
      {result && (
        <pre style={{ background: "#f3f4f6", padding: 12, borderRadius: 6 }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}
