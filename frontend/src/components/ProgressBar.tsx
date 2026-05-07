import { useEffect, useState } from "react";

interface ProgressEvent {
  event: string;
  data: Record<string, any>;
}

export function ProgressBar({ sessionId }: { sessionId: number | null }) {
  const [latest, setLatest] = useState<ProgressEvent | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${location.host}/ws/sessions/${sessionId}/progress`
    );
    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as ProgressEvent;
        if (payload.event !== "ping") setLatest(payload);
      } catch {}
    };
    ws.onerror = () => setLatest({ event: "error", data: {} });
    return () => ws.close();
  }, [sessionId]);

  if (!sessionId || !latest) return null;
  const { event, data } = latest;
  let pct: number | null = null;
  let label = event;
  if ("page" in data && "total" in data) {
    pct = (data.page / data.total) * 100;
    label = `Parsing página ${data.page}/${data.total}`;
  } else if ("done" in data && "total" in data) {
    pct = (data.done / data.total) * 100;
    label = `Detectando menções ${data.done}/${data.total} (${data.mentions ?? 0} encontradas)`;
  } else if ("batch" in data && "total_batches" in data) {
    pct = (data.batch / data.total_batches) * 100;
    label = `Classificando lote ${data.batch}/${data.total_batches} (mantidos ${data.kept}, descartados ${data.dropped})`;
  } else if (event === "batch_proposal_progress") {
    pct = (data.done / data.total) * 100;
    label = `Gerando propostas em lote ${data.done}/${data.total}`;
  } else if (event === "parse_done") {
    label = `Parse concluído (${data.total} páginas)`;
    pct = 100;
  } else if (event === "detect_done") {
    label = `Detecção concluída (${data.mentions ?? 0} menções, classifier=${data.classified ? "sim" : "não"})`;
    pct = 100;
  } else if (event === "batch_proposal_done") {
    label = `Propostas em lote concluídas (${data.done ?? data.total} processadas)`;
    pct = 100;
  }

  return (
    <div style={{ margin: "12px 0" }}>
      <div className="muted" style={{ marginBottom: 4 }}>{label}</div>
      {pct != null && (
        <div className="progress-bar">
          <div style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}
