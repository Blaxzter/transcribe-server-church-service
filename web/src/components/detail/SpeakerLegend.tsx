import { useMemo, useState } from "react";
import { Pencil } from "lucide-react";
import type { Transcript } from "@/lib/api";
import { de } from "@/i18n/de";
import { withAlpha } from "@/lib/utils";
import { PanelHeading } from "@/components/detail/PanelHeading";
import { RenameSpeakerDialog } from "@/components/detail/RenameSpeakerDialog";
import { Button } from "@/components/ui/button";

interface SpeakerLegendProps {
  doc: Transcript | null;
  onRenameSpeaker?: (speakerId: string, label: string) => Promise<void>;
}

/** Speakers with how much of the service each of them actually speaks. */
export function SpeakerLegend({ doc, onRenameSpeaker }: SpeakerLegendProps) {
  const [renaming, setRenaming] = useState<string | null>(null);

  const speakers = useMemo(() => {
    if (!doc) return [];
    const seconds = new Map<string, number>();
    for (const segment of doc.segments) {
      if (segment.type !== "speech" || !segment.speaker) continue;
      const spoken = Math.max(0, segment.end - segment.start);
      seconds.set(segment.speaker, (seconds.get(segment.speaker) ?? 0) + spoken);
    }
    const total = [...seconds.values()].reduce((sum, value) => sum + value, 0);
    return Object.entries(doc.speakers).map(([id, speaker]) => ({
      id,
      label: speaker.label,
      color: speaker.color,
      share: total > 0 ? (seconds.get(id) ?? 0) / total : 0,
    }));
  }, [doc]);

  return (
    <>
      <PanelHeading title={de.detail.tabSpeakers} />
      <ul className="space-y-1.5">
        {speakers.map((speaker) => (
          <li
            key={speaker.id}
            className="group flex items-center gap-2.5 rounded-md py-1 pl-2.5 pr-1"
            style={{ background: withAlpha(speaker.color, 0.12) }}
          >
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ background: speaker.color }}
            />
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {speaker.label}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {Math.round(speaker.share * 100)} %
            </span>
            {onRenameSpeaker && (
              <Button
                size="icon-sm"
                variant="ghost"
                className="shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
                title={de.transcript.renameSpeaker}
                aria-label={`${de.transcript.renameSpeaker}: ${speaker.label}`}
                onClick={() => setRenaming(speaker.id)}
              >
                <Pencil />
              </Button>
            )}
          </li>
        ))}
      </ul>

      {renaming && onRenameSpeaker && (
        <RenameSpeakerDialog
          key={renaming}
          currentLabel={doc?.speakers[renaming]?.label ?? renaming}
          onSave={(label) => onRenameSpeaker(renaming, label)}
          onClose={() => setRenaming(null)}
        />
      )}
    </>
  );
}
