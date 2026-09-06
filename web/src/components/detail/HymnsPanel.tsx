import { Play } from "lucide-react";
import type { Hymn } from "@/lib/api";
import { de } from "@/i18n/de";
import { cn, formatTime } from "@/lib/utils";
import { PanelHeading } from "@/components/detail/PanelHeading";

interface HymnsPanelProps {
  hymns: Hymn[];
  onSeek?: (seconds: number) => void;
}

/**
 * The hymns of a service.
 *
 * Two sources, because neither is sufficient alone: the recording, which gives
 * a timestamp to jump to but only announces about a quarter of them aloud, and
 * the filename, which carries them for most services but has no timing. Entries
 * known only from the filename are shown without a play control rather than
 * with a dead one.
 */
export function HymnsPanel({ hymns, onSeek }: HymnsPanelProps) {
  if (hymns.length === 0) {
    return (
      <>
        <PanelHeading title={de.hymns.title} />
        <p className="text-sm text-muted-foreground">{de.hymns.empty}</p>
      </>
    );
  }

  const spoken = hymns.filter((hymn) => hymn.at !== null).length;

  return (
    <>
      <PanelHeading title={de.hymns.title} />
      <ul className="space-y-1">
        {hymns.map((hymn) => {
          const seekable = hymn.at !== null && Boolean(onSeek);
          return (
            <li key={hymn.number}>
              <button
                type="button"
                disabled={!seekable}
                onClick={() => hymn.at !== null && onSeek?.(hymn.at)}
                title={hymn.context ?? undefined}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors",
                  seekable ? "hover:bg-accent" : "cursor-default opacity-70",
                )}
              >
                <span className="min-w-[2.75rem] rounded bg-secondary px-2 py-0.5 text-center font-mono text-sm font-medium tabular-nums">
                  {hymn.number}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                  {hymn.context ?? de.hymns.fromTitle}
                </span>
                {hymn.at !== null && (
                  <span className="inline-flex shrink-0 items-center gap-1 font-mono text-xs tabular-nums text-muted-foreground">
                    <Play className="size-3" />
                    {formatTime(hymn.at)}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-muted-foreground">
        {spoken > 0 ? de.hymns.hint(spoken, hymns.length) : de.hymns.noneSpoken}
      </p>
    </>
  );
}
