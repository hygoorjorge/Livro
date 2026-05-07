const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  listLaws: () => request<{ id: number; identifier: string; kind: string }[]>("/laws"),
  uploadLaw: (form: FormData) =>
    request<{ id: number }>("/laws", { method: "POST", body: form }),
  listMappings: () =>
    request<{ id: number; obsolete_ref: string; vigent_law_id: number; notes?: string }[]>(
      "/laws/mappings"
    ),
  createMapping: (payload: { obsolete_ref: string; vigent_law_id: number; notes?: string }) =>
    request<{ id: number }>("/laws/mappings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  uploadPdf: (form: FormData) =>
    request<{ session_id: number; status: string }>("/pdf/upload", {
      method: "POST",
      body: form,
    }),
  listSessions: () =>
    request<{ id: number; name: string; status: string }[]>("/sessions"),

  detect: (sid: number, useClassifier = true) =>
    request<{ queued: boolean; classifier: boolean }>(
      `/mentions/${sid}/detect?use_classifier=${useClassifier}`,
      { method: "POST" }
    ),
  batchGenerate: (sid: number) =>
    request<{ queued: boolean }>(`/proposals/${sid}/batch`, { method: "POST" }),
  listMentions: (sid: number, status?: string) =>
    request<any[]>(`/mentions/${sid}${status ? `?status=${status}` : ""}`),
  listHighlights: (sid: number) =>
    request<any[]>(`/mentions/${sid}/highlights`),
  setMentionStatus: (mentionId: number, status: string) =>
    request<any>(`/mentions/${mentionId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),

  generateAuto: (mentionId: number) =>
    request<any>(`/proposals/auto/${mentionId}`, { method: "POST" }),
  generateManual: (mentionId: number, finalText: string) =>
    request<any>(`/proposals/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mention_id: mentionId, final_text: finalText }),
    }),
  acceptProposal: (id: number, editedText?: string) =>
    request<any>(`/proposals/${id}/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edited_text: editedText ?? null }),
    }),
  rejectProposal: (id: number) =>
    request<any>(`/proposals/${id}/reject`, { method: "POST" }),
  proposalsForMention: (mentionId: number) =>
    request<any[]>(`/proposals/by-mention/${mentionId}`),

  scanFigures: (sid: number) =>
    request<{ flagged: number }>(`/figures/${sid}/scan`, { method: "POST" }),
  listFigures: (sid: number) => request<any[]>(`/figures/${sid}`),
  keepFigure: (id: number) =>
    request<any>(`/figures/${id}/keep`, { method: "POST" }),
  replaceFigure: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<any>(`/figures/${id}/replace`, { method: "POST", body: fd });
  },

  exportSession: (sid: number) =>
    request<any>(`/verify/${sid}/export`, { method: "POST" }),
  runVerification: (sid: number) =>
    request<{ passed: boolean; total_diffs: number; unauthorized_diffs: any[] }>(
      `/verify/${sid}/run`,
      { method: "POST" }
    ),
};
