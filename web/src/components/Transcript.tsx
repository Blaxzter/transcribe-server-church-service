import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Music, Search } from "lucide-react";
import type { Segment, Transcript as TranscriptDoc } from "@/lib/api";
import { cn, formatTime } from "@/lib/utils";
import { de } from "@/i18n/de";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface TranscriptProps {
  doc: TranscriptDoc;
  currentTime: number;
  onSeek: (seconds: number) => void;
  onEditSegment: (id: string, text: string) => Promise<void>;
  onRenameSpeaker: (speakerId: string, label: string) => Promise<void>;
}

/**
 * Virtualized transcript.
 *
 * A 90-minute service is a few thousand segments; rendering them all locks up a
 * weak laptop for seconds on every keystroke. Only the visible window is in the
 * DOM.
 */
export function TranscriptView({
  doc,
  currentTime,
  onSeek,
  onEditSegment,
  onRenameSpeaker,
}: TranscriptProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  const segments = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return doc.segments;
    return doc.segments.filter((s) => s.text.toLowerCase().includes(needle));
  }, [doc.segments, query]);

  const activeIndex = useMemo(() => {
    if (!segments.length) return -1;
    // Segments are ordered, so a binary search keeps this off the hot path.
    let low = 0;
    let high = segments.length - 1;
    let found = -1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (segments[mid].start <= currentTime) {
        found = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    if (found >= 0 && currentTime > segments[found].end + 1) return -1;
    return found;
  }, [segments, currentTime]);

  const virtualizer = useVirtualizer({
    count: segments.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 96,
    overscan: 8,
    measureElement: (element) => element.getBoundingClientRect().height,
  });

  useEffect(() => {
    if (!follow || activeIndex < 0 || editingId) return;
    virtualizer.scrollToIndex(activeIndex, { align: "center", behavior: "smooth" });
  }, [activeIndex, follow, editingId, virtualizer]);

  const commitEdit = useCallback(
    async (segment: Segment, text: string) => {
      setEditingId(null);
      if (text.trim() !== segment.text.trim()) {
        await onEditSegment(segment.id, text.trim());
      }
    },
    [onEditSegment],
  );

  const items = virtualizer.getVirtualItems();

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={de.transcript.search}
            className="pl-8"
          />
        </div>
        <Button
          variant={follow ? "default" : "outline"}
          size="sm"
          onClick={() => setFollow((value) => !value)}
          title={de.transcript.followPlayback}
        >
          {de.transcript.followPlayback}
        </Button>
      </div>

      {segments.length === 0 ? (
        <p className="p-8 text-center text-sm text-muted-foreground">
          {query ? de.transcript.noResults : de.jobs.empty}
        </p>
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-2 py-2">
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {items.map((item) => {
              const segment = segments[item.index];
              const speaker = segment.speaker ? doc.speakers[segment.speaker] : undefined;
              const isActive = item.index === activeIndex;
              return (
                <div
                  key={segment.id}
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  className="absolute left-0 top-0 w-full"
                  style={{ transform: `translateY(${item.start}px)` }}
                >
                  <SegmentRow
                    segment={segment}
                    speakerLabel={speaker?.label}
                    speakerColor={speaker?.color}
                    active={isActive}
                    editing={editingId === segment.id}
                    onSeek={() => onSeek(segment.start)}
                    onStartEdit={() => setEditingId(segment.id)}
                    onCommit={(text) => commitEdit(segment, text)}
                    onCancel={() => setEditingId(null)}
                    onRenameSpeaker={() =>
                      segment.speaker && setRenaming(segment.speaker)
                    }
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {renaming && (
        <RenameSpeakerDialog
          currentLabel={doc.speakers[renaming]?.label ?? renaming}
          onCancel={() => setRenaming(null)}
          onSave={async (label) => {
            const id = renaming;
            setRenaming(null);
            await onRenameSpeaker(id, label);
          }}
        />
      )}
    </div>
  );
}

interface SegmentRowProps {
  segment: Segment;
  speakerLabel?: string;
  speakerColor?: string;
  active: boolean;
  editing: boolean;
  onSeek: () => void;
  onStartEdit: () => void;
  onCommit: (text: string) => void;
  onCancel: () => void;
  onRenameSpeaker: () => void;
}

function SegmentRow({
  segment,
  speakerLabel,
  speakerColor,
  active,
  editing,
  onSeek,
  onStartEdit,
  onCommit,
  onCancel,
  onRenameSpeaker,
}: SegmentRowProps) {
  const [draft, setDraft] = useState(segment.text);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editing) return;
    setDraft(segment.text);
    const node = textareaRef.current;
    if (node) {
      node.focus();
      node.setSelectionRange(node.value.length, node.value.length);
      node.style.height = "auto";
      node.style.height = `${node.scrollHeight}px`;
    }
  }, [editing, segment.text]);

  if (segment.type === "music") {
    return (
      <button
        type="button"
        onClick={onSeek}
        className={cn(
          "my-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors",
          "text-muted-foreground hover:bg-accent",
          active && "bg-accent",
        )}
      >
        <span className="font-mono text-xs tabular-nums opacity-70">
          {formatTime(segment.start)}
        </span>
        <Music className="size-4 shrink-0 opacity-70" />
        <span className="text-sm italic">{segment.text}</span>
        <span className="ml-auto font-mono text-xs tabular-nums opacity-50">
          {formatTime(segment.end - segment.start)}
        </span>
      </button>
    );
  }

  return (
    <div
      className={cn(
        "my-1 rounded-md px-3 py-2.5 transition-colors",
        active ? "bg-accent" : "hover:bg-accent/60",
      )}
    >
      <div className="mb-1 flex items-center gap-2">
        <button
          type="button"
          onClick={onSeek}
          className="font-mono text-xs tabular-nums text-muted-foreground hover:underline"
        >
          {formatTime(segment.start)}
        </button>
        {speakerLabel && (
          <button
            type="button"
            onClick={onRenameSpeaker}
            title={de.transcript.renameSpeaker}
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium hover:underline"
            style={{ color: speakerColor, background: `${speakerColor}1a` }}
          >
            <span
              className="size-1.5 rounded-full"
              style={{ background: speakerColor }}
            />
            {speakerLabel}
          </button>
        )}
        {segment.edited && (
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            bearbeitet
          </span>
        )}
      </div>

      {editing ? (
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            event.target.style.height = "auto";
            event.target.style.height = `${event.target.scrollHeight}px`;
          }}
          onBlur={() => onCommit(draft)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onCancel();
            }
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              onCommit(draft);
            }
          }}
          className="w-full resize-none rounded-md border border-input bg-background p-2 text-sm leading-relaxed outline-none focus:ring-2 focus:ring-ring"
          rows={1}
        />
      ) : (
        <p
          onClick={onStartEdit}
          className="cursor-text text-sm leading-relaxed"
          title={de.transcript.editHint}
        >
          {segment.text}
        </p>
      )}
    </div>
  );
}

function RenameSpeakerDialog({
  currentLabel,
  onSave,
  onCancel,
}: {
  currentLabel: string;
  onSave: (label: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(currentLabel);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="mb-3 font-semibold">{de.transcript.renameSpeaker}</h2>
        <label className="mb-1.5 block text-sm text-muted-foreground">
          {de.transcript.speakerName}
        </label>
        <Input
          autoFocus
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && value.trim()) onSave(value.trim());
            if (event.key === "Escape") onCancel();
          }}
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {de.transcript.cancel}
          </Button>
          <Button disabled={!value.trim()} onClick={() => onSave(value.trim())}>
            {de.transcript.save}
          </Button>
        </div>
      </div>
    </div>
  );
}
