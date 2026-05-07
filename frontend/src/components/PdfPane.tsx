import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import * as pdfjsLib from "pdfjs-dist";
// Vite-specific worker import — bundles the PDF.js worker as a separate chunk.
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

export interface Highlight {
  mention_id: number;
  page_num: number;
  bbox: [number, number, number, number];
  raw_text: string;
  detected_ref: string;
  is_historical: boolean;
  status: string;
  paragraph_id: number;
}

export interface PdfPaneHandle {
  scrollToMention: (mentionId: number) => void;
}

interface Props {
  url: string;
  highlights: Highlight[];
  activeMentionId?: number | null;
  onHighlightClick?: (mentionId: number) => void;
}

const COLOR_BY_STATUS: Record<string, string> = {
  pending: "rgba(250, 204, 21, 0.35)",
  awaiting_user_decision: "rgba(248, 113, 113, 0.4)",
  confirmed: "rgba(96, 165, 250, 0.35)",
  dismissed: "rgba(156, 163, 175, 0.25)",
};

export const PdfPane = forwardRef<PdfPaneHandle, Props>(function PdfPane(
  { url, highlights, activeMentionId, onHighlightClick },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const [pageDims, setPageDims] = useState<Map<number, { width: number; height: number }>>(
    new Map()
  );
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(1.2);
  const [error, setError] = useState<string | null>(null);

  useImperativeHandle(ref, () => ({
    scrollToMention(mentionId: number) {
      const h = highlights.find((h) => h.mention_id === mentionId);
      if (!h) return;
      const el = pageRefs.current.get(h.page_num);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    },
  }));

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const task = pdfjsLib.getDocument(url);
    task.promise
      .then(async (doc) => {
        if (cancelled) return;
        setNumPages(doc.numPages);
        const dims = new Map<number, { width: number; height: number }>();
        for (let i = 1; i <= doc.numPages; i++) {
          const page = await doc.getPage(i);
          const viewport = page.getViewport({ scale });
          dims.set(i, { width: viewport.width, height: viewport.height });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          const ctx = canvas.getContext("2d")!;
          await page.render({ canvasContext: ctx, viewport, canvas }).promise;
          if (cancelled) return;
          const wrap = pageRefs.current.get(i);
          if (wrap) {
            wrap.querySelectorAll("canvas").forEach((c) => c.remove());
            wrap.prepend(canvas);
          }
        }
        if (!cancelled) setPageDims(dims);
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [url, scale]);

  if (error) return <pre style={{ color: "#b91c1c" }}>PDF error: {error}</pre>;

  return (
    <div ref={containerRef} className="pdf-pane">
      <div className="pdf-toolbar">
        <button onClick={() => setScale((s) => Math.max(0.5, s - 0.2))}>−</button>
        <span className="muted">zoom {(scale * 100).toFixed(0)}%</span>
        <button onClick={() => setScale((s) => Math.min(3, s + 0.2))}>+</button>
        <span className="muted">{numPages} páginas</span>
      </div>
      {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
        const dims = pageDims.get(pageNum);
        const pageHighlights = highlights.filter((h) => h.page_num === pageNum);
        return (
          <div
            key={pageNum}
            ref={(el) => {
              if (el) pageRefs.current.set(pageNum, el);
              else pageRefs.current.delete(pageNum);
            }}
            className="pdf-page"
            style={{
              width: dims?.width ?? "auto",
              height: dims?.height ?? "auto",
              position: "relative",
            }}
          >
            {dims &&
              pageHighlights.map((h) => {
                const [x0, y0, x1, y1] = h.bbox;
                const isActive = activeMentionId === h.mention_id;
                return (
                  <div
                    key={h.mention_id}
                    className="pdf-highlight"
                    title={`${h.raw_text} → ${h.detected_ref}`}
                    onClick={() => onHighlightClick?.(h.mention_id)}
                    style={{
                      left: x0 * scale,
                      top: y0 * scale,
                      width: Math.max(8, (x1 - x0) * scale),
                      height: Math.max(8, (y1 - y0) * scale),
                      background:
                        COLOR_BY_STATUS[h.status] ?? "rgba(250, 204, 21, 0.35)",
                      outline: isActive ? "2px solid #2563eb" : "1px solid transparent",
                    }}
                  />
                );
              })}
            <div className="pdf-page-label">p. {pageNum}</div>
          </div>
        );
      })}
    </div>
  );
});
