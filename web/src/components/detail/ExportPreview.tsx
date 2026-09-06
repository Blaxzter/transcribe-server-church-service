import { useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { de } from "@/i18n/de";
import { cn } from "@/lib/utils";

export type Preview =
  | { kind: "text"; text: string }
  | { kind: "docx"; blob: Blob }
  | { kind: "error"; message?: string };

/**
 * What the file will look like, filling whatever space it is given. `null` is
 * the very first build; every later one keeps the previous page on screen and
 * is dimmed by the caller instead, so ticking a switch does not blank the
 * panel for half a second.
 */
export function ExportPreview({ preview }: { preview: Preview | null }) {
  if (preview === null) {
    return (
      <Notice>
        <Loader2 className="size-4 animate-spin" />
        {de.exportDialog.previewLoading}
      </Notice>
    );
  }
  if (preview.kind === "error") {
    return (
      <Notice destructive>
        <AlertCircle className="size-4 shrink-0" />
        {preview.message ?? de.exportDialog.previewFailed}
      </Notice>
    );
  }
  if (preview.kind === "text") {
    if (!preview.text.trim()) {
      return <Notice>{de.exportDialog.previewEmpty}</Notice>;
    }
    return (
      <div className="min-h-0 flex-1 overflow-auto">
        <pre className="whitespace-pre-wrap break-words p-5 font-mono text-xs leading-relaxed">
          {preview.text}
        </pre>
      </div>
    );
  }
  return <DocxPaper blob={preview.blob} />;
}

function Notice({
  destructive,
  children,
}: {
  destructive?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-0 flex-1 place-items-center">
      <p
        className={cn(
          "flex items-center gap-2 p-4 text-sm",
          destructive ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {children}
      </p>
    </div>
  );
}

/**
 * The .docx the server just produced, drawn as the sheet of paper it will be
 * printed on.
 *
 * docx-preview lays a page out in real print units — an A4 page is close to
 * 800 CSS pixels wide. Letting it reflow into a narrower panel (its
 * `ignoreWidth`) keeps the margins at their full size, which is what made the
 * old preview look like a column of text pinched between two enormous
 * borders. So the page keeps its true size and the whole stack is scaled down
 * to the width of the panel instead; margins then sit in the same proportion
 * as on paper.
 */
function DocxPaper({ blob }: { blob: Blob }) {
  const pagesRef = useRef<HTMLDivElement>(null);
  const rulerRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState<{ width: number; height: number } | null>(null);
  const [available, setAvailable] = useState(0);
  const [failed, setFailed] = useState(false);

  // The renderer is loaded on first use; most visits never open this dialog.
  useEffect(() => {
    const host = pagesRef.current;
    if (!host) return;
    let cancelled = false;
    setFailed(false);
    import("docx-preview")
      .then(({ renderAsync }) => {
        if (cancelled) return;
        host.replaceChildren();
        return renderAsync(blob, host, undefined, {
          inWrapper: false,
          breakPages: true,
          useBase64URL: true,
        });
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [blob]);

  // Both sizes are watched rather than measured once: the pages grow when the
  // embedded font finishes loading and reflows the text, and the panel is
  // resized whenever the window is.
  useEffect(() => {
    const host = pagesRef.current;
    const ruler = rulerRef.current;
    if (!host || !ruler) return;
    const measure = () => {
      const first = host.querySelector("section");
      // offsetWidth and scrollHeight are layout values, so the scale we put on
      // this very element does not feed back into them. Same size, same object:
      // the width we set from this feeds back into the observer otherwise.
      if (first) {
        const width = first.offsetWidth;
        const height = host.scrollHeight;
        setPage((current) =>
          current && current.width === width && current.height === height
            ? current
            : { width, height },
        );
      }
      setAvailable(ruler.clientWidth);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    observer.observe(ruler);
    return () => observer.disconnect();
  }, [blob]);

  const scale = page && available ? Math.min(1, available / page.width) : 1;

  return (
    // A stable scrollbar gutter keeps the ruler's width from changing the
    // moment the pages get tall enough to scroll, which would otherwise leave
    // the sheet a scrollbar too wide until the observer caught up.
    <div className="min-h-0 flex-1 overflow-auto p-5 [scrollbar-gutter:stable]">
      {failed && (
        <p className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          {de.exportDialog.previewFailed}
        </p>
      )}
      <div ref={rulerRef} className="h-0 w-full" aria-hidden />
      {/* Kept mounted even after a failure: the next build renders into it. */}
      <div
        className={cn("mx-auto", failed && "hidden")}
        style={page ? { width: page.width * scale, height: page.height * scale } : undefined}
      >
        <div
          ref={pagesRef}
          className="docx-paper origin-top-left"
          style={{ width: page?.width, transform: `scale(${scale})` }}
        />
      </div>
    </div>
  );
}
