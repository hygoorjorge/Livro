import { create } from "zustand";

interface SessionState {
  sessionId: number | null;
  setSessionId: (id: number | null) => void;
}

export const useSession = create<SessionState>((set) => ({
  sessionId: Number(localStorage.getItem("sessionId")) || null,
  setSessionId: (id) => {
    if (id == null) localStorage.removeItem("sessionId");
    else localStorage.setItem("sessionId", String(id));
    set({ sessionId: id });
  },
}));
