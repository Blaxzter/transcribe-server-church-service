import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Copy, FileText, Music, SearchX } from "lucide-react";
import type { Segment, Transcript as TranscriptDoc } from "@/lib/api";
import { cn, formatTime, withAlpha } from "@/lib/utils";
import { de } from "@/i18n/de";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SearchInput } from "@/components/ui/search-input";
import { Switch } from "@/components/ui/switch";
import { Tooltip } from "@/components/ui/tooltip";
import { EmptyState } from "@/components/ui/empty-state";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";

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
 * DOM, and every row callback is stable so a playback tick re-renders the two
 * rows whose active state actually changed rather than the whole window.
 */
export function TranscriptView({
  doc,
  currentTime,
  onSeek,
  onEditSegment,
  onRenameSpeaker,
}: TranscriptProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  const needle = query.trim().toLowerCase();

  const segments = useMemo(() => {
    if (!needle) return doc.segments;
    return doc.segments.filter((s) => s.text.toLowerCase().includes(needle));
  }, [doc.segments, needle]);

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
    // Without this the measured-height cache is keyed by position, so filtering
    // by the search box would hand a row the height of whatever segment used to
    // sit in that slot.
    getItemKey: (index) => segments[index]?.id ?? index,
    overscan: 8,
    measureElement: (element) => element.getBoundingClientRect().height,
  });

  useEffect(() => {
    if (!follow || activeIndex < 0 || editingId) return;
    virtualizer.scrollToIndex(activeIndex, { align: "center", behavior: "smooth" });
  }, [activeIndex, follow, editingId, virtualizer]);

  const startEdit = useCallback((id: string) => setEditingId(id), []);
  const cancelEdit = useCallback(() => setEditingId(null), []);
  const startRename = useCallback((speakerId: string) => setRenaming(speakerId), []);

  const commitEdit = useCallback(
    async (segment: Segment, text: string) => {
      setEditingId(null);
      if (text.trim() !== segment.text.trim()) {
        await onEditSegment(segment.id, text.trim());
      }
    },
    [onEditSegment],
  );

  const copyAll = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(plainText(doc));
      toast({ title: de.toast.copied, variant: "success" });
    } catch {
      toast({ title: de.toast.copyFailed, variant: "destructive" });
    }
  }, [doc, toast]);

  const items = virtualizer.getVirtualItems();

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
        <SearchInput
          value={query}
          onValueChange={setQuery}
          placeholder={de.transcript.search}
          aria-label={de.transcript.search}
          wrapperClassName="min-w-48 flex-1"
        />
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {needle
            ? `${segments.length} ${de.transcript.resultCount}`
            : `${doc.segments.length} ${de.transcript.segments}`}
        </span>
        <Switch
          checked={follow}
          onCheckedChange={setFollow}
          label={de.transcript.followPlayback}
          className="shrink-0"
        />
        <Tooltip label={de.transcript.copyAll} side="left">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => void copyAll()}
            aria-label={de.transcript.copyAll}
          >
            <Copy />
          </Button>
        </Tooltip>
      </div>

      {segments.length === 0 ? (
        needle ? (
          <EmptyState
            className="flex-1"
            icon={<SearchX />}
            title={de.transcript.noResults}
            description={de.jobs.searchEmptyHint}
            action={
              <Button variant="outline" size="sm" onClick={() => setQuery("")}>
                {de.common.clear}
              </Button>
            }
          />
        ) : (
          <EmptyState className="flex-1" icon={<FileText />} title={de.transcript.empty} />
        )
      ) : (
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto overscroll-contain px-2 py-2"
        >
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {items.map((item) => {
              const segment = segments[item.index];
              const speaker = segment.speaker ? doc.speakers[segment.speaker] : undefined;
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
                    needle={needle}
                    active={item.index === activeIndex}
                    editing={editingId === segment.id}
                    onSeek={onSeek}
                    onStartEdit={startEdit}
                    onCommit={commitEdit}
                    onCancel={cancelEdit}
                    onRenameSpeaker={startRename}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {renaming && (
        <RenameSpeakerDialog
          key={renaming}
          currentLabel={doc.speakers[renaming]?.label ?? renaming}
          onClose={() => setRenaming(null)}
          onSave={(label) => onRenameSpeaker(renaming, label)}
        />
      )}
    </div>
  );
}

interface SegmentRowProps {
  segment: Segment;
  speakerLabel?: string;
  speakerColor?: string;
  /** Lower-cased search term, highlighted inside the text. */
  needle: string;
  active: boolean;
  editing: boolean;
  onSeek: (seconds: number) => void;
  onStartEdit: (id: string) => void;
  onCommit: (segment: Segment, text: string) => void;
  onCancel: () => void;
  onRenameSpeaker: (speakerId: string) => void;
}

const SegmentRow = memo(function SegmentRow({
  segment,
  speakerLabel,
  speakerColor,
  needle,
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

  const speakerId = segment.speaker ?? null;

  if (segment.type === "music") {
    return (
      <button
        type="button"
        onClick={() => onSeek(segment.start)}
        title={de.transcript.jumpTo}
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
        <span className="text-sm italic">{segment.text || de.transcript.music}</span>
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
          onClick={() => onSeek(segment.start)}
          title={de.transcript.jumpTo}
          className="rounded-sm font-mono text-xs tabular-nums text-muted-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {formatTime(segment.start)}
        </button>
        {speakerLabel && speakerId && (
          <button
            type="button"
            onClick={() => onRenameSpeaker(speakerId)}
            title={de.transcript.renameSpeaker}
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            style={
              speakerColor
                ? { color: speakerColor, background: withAlpha(speakerColor, 0.12) }
                : undefined
            }
          >
            <span
              className="size-1.5 rounded-full bg-current"
              style={speakerColor ? { background: speakerColor } : undefined}
            />
            {speakerLabel}
          </button>
        )}
        {segment.edited && (
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {de.transcript.edited}
          </span>
        )}
      </div>

      {editing ? (
        <Textarea
          ref={textareaRef}
          value={draft}
          rows={1}
          onChange={(event) => {
            setDraft(event.target.value);
            event.target.style.height = "auto";
            event.target.style.height = `${event.target.scrollHeight}px`;
          }}
          onBlur={() => onCommit(segment, draft)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onCancel();
            }
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              onCommit(segment, draft);
            }
          }}
          className="bg-background"
        />
      ) : (
        <p
          onClick={() => onStartEdit(segment.id)}
          className="cursor-text text-sm leading-relaxed"
          title={de.transcript.editHint}
        >
          <Highlight text={segment.text} needle={needle} />
        </p>
      )}
    </div>
  );
});

/** Marks every occurrence of an already lower-cased needle. */
function Highlight({ text, needle }: { text: string; needle: string }) {
  if (!needle) return <>{text}</>;

  const parts: ReactNode[] = [];
  const haystack = text.toLowerCase();
  let cursor = 0;
  let at = haystack.indexOf(needle);
  while (at >= 0) {
    if (at > cursor) parts.push(text.slice(cursor, at));
    parts.push(
      <mark key={at} className="rounded-sm bg-warning/25 text-inherit">
        {text.slice(at, at + needle.length)}
      </mark>,
    );
    cursor = at + needle.length;
    at = haystack.indexOf(needle, cursor);
  }
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}

function RenameSpeakerDialog({
  currentLabel,
  onSave,
  onClose,
}: {
  currentLabel: string;
  onSave: (label: string) => Promise<void>;
  onClose: () => void;
}) {
  const [value, setValue] = useState(currentLabel);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const label = value.trim();

  const save = async () => {
    if (!label || pending) return;
    setPending(true);
    try {
      await onSave(label);
      onClose();
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !pending && onClose()}
      title={de.transcript.renameSpeaker}
      initialFocusRef={inputRef}
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={onClose}>
            {de.transcript.cancel}
          </Button>
          <Button disabled={!label || pending} onClick={() => void save()}>
            {de.transcript.save}
          </Button>
        </>
      }
    >
      <label className="mb-1.5 block text-sm text-muted-foreground" htmlFor="speaker-name">
        {de.transcript.speakerName}
      </label>
      <Input
        id="speaker-name"
        ref={inputRef}
        value={value}
        disabled={pending}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void save();
          }
        }}
      />
    </Dialog>
  );
}

/** Flat text for the clipboard: "12:34  Sprecher: Text". */
function plainText(doc: TranscriptDoc): string {
  return doc.segments
    .map((segment) => {
      const time = formatTime(segment.start);
      if (segment.type === "music") {
        return `${time}  [${segment.text || de.transcript.music}]`;
      }
      const speaker = segment.speaker ? doc.speakers[segment.speaker]?.label : undefined;
      return speaker ? `${time}  ${speaker}: ${segment.text}` : `${time}  ${segment.text}`;
    })
    .join("\n");
}
