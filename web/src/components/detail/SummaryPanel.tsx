import { Copy } from "lucide-react";
import type { Transcript } from "@/lib/api";
import { de } from "@/i18n/de";
import { PanelHeading } from "@/components/detail/PanelHeading";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";

interface SummaryPanelProps {
  doc: Transcript | null;
  legacy: boolean;
}

/**
 * The summary is multi-paragraph prose and can be longer than the whole
 * sidebar; it scrolls inside its tab panel instead of stretching the page.
 */
export function SummaryPanel({ doc, legacy }: SummaryPanelProps) {
  const { toast } = useToast();
  const summary = doc?.summary ?? "";
  const outline = doc?.outline ?? [];

  const copy = async () => {
    const text = outline.length
      ? `${summary}\n\n${outline.map((item) => `• ${item}`).join("\n")}`
      : summary;
    try {
      await navigator.clipboard.writeText(text);
      toast({ title: de.toast.copied, variant: "success" });
    } catch {
      toast({ title: de.toast.copyFailed, variant: "destructive" });
    }
  };

  if (!summary) {
    return (
      <>
        <PanelHeading title={de.summary.title} />
        <p className="text-sm text-muted-foreground">{de.summary.missing}</p>
        {legacy && (
          <p className="mt-2 text-xs text-muted-foreground">{de.transcript.imported}</p>
        )}
      </>
    );
  }

  return (
    <>
      <PanelHeading title={de.summary.title}>
        {/* Left, not top: the heading sits flush against the top of a
            scrolling panel, where a bubble above the button is clipped away. */}
        <Tooltip label={de.summary.copy} side="left">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={de.summary.copy}
            onClick={() => void copy()}
          >
            <Copy />
          </Button>
        </Tooltip>
      </PanelHeading>

      <div className="space-y-4">
        <p className="whitespace-pre-line text-sm leading-relaxed">{summary}</p>
        {outline.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {de.summary.outline}
            </h4>
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              {outline.map((item, index) => (
                <li key={index} className="flex gap-2">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-muted-foreground/60" />
                  <span className="min-w-0">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </>
  );
}
