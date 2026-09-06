import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import type { Job } from "@/lib/api";
import { cn, groupByTime, jobDate } from "@/lib/utils";
import { JobRow } from "@/components/jobs/JobRow";

type ListRow =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "job"; key: string; job: Job };

const HEADER_HEIGHT = 40;
const ROW_HEIGHT = 78;

interface JobListProps {
  /** Already filtered and sorted; this component only groups and draws. */
  jobs: Job[];
  grouped: boolean;
  onDelete: (job: Job) => void;
  onRetry: (job: Job) => void;
}

/**
 * The recordings list.
 *
 * A hundred and twenty services with a progress bar and a menu each is more DOM
 * than a modest machine wants to keep around, so only the visible window is
 * rendered. It scrolls with the page rather than in a box of its own: a list
 * this long inside a fixed-height pane is exactly what the transcript view
 * already does, and doing it twice on one screen reads as broken.
 */
export function JobList({ jobs, grouped, onDelete, onRetry }: JobListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const [scrollMargin, setScrollMargin] = useState(0);

  const rows = useMemo<ListRow[]>(() => {
    if (!grouped) {
      return jobs.map((job) => ({ type: "job", key: job.id, job }));
    }
    const out: ListRow[] = [];
    for (const group of groupByTime(jobs, jobDate)) {
      out.push({
        type: "header",
        key: `group:${group.key}`,
        label: group.label,
        count: group.items.length,
      });
      for (const job of group.items) out.push({ type: "job", key: job.id, job });
    }
    return out;
  }, [jobs, grouped]);

  // The list sits an unknown distance down the page and the uploader above it
  // grows while a file is in flight, so the offset has to be re-measured
  // whenever the layout moves.
  useLayoutEffect(() => {
    const node = listRef.current;
    if (!node) return;
    const measure = () => {
      const top = node.getBoundingClientRect().top + window.scrollY;
      setScrollMargin((current) => (Math.abs(current - top) > 1 ? top : current));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(document.body);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: (index) =>
      rows[index].type === "header" ? HEADER_HEIGHT : ROW_HEIGHT,
    getItemKey: (index) => rows[index].key,
    overscan: 6,
    scrollMargin,
    measureElement: (element) => element.getBoundingClientRect().height,
  });

  const items = virtualizer.getVirtualItems();

  return (
    <div
      ref={listRef}
      className="relative w-full overflow-hidden rounded-lg border border-border bg-card"
      style={{ height: virtualizer.getTotalSize() }}
    >
      {items.map((item) => {
        const row = rows[item.index];
        // The card already draws the outer line; a border on the last row
        // would double it.
        const divider = item.index < rows.length - 1;
        return (
          <div
            key={item.key}
            data-index={item.index}
            ref={virtualizer.measureElement}
            className="absolute left-0 top-0 w-full"
            style={{ transform: `translateY(${item.start - scrollMargin}px)` }}
          >
            {row.type === "header" ? (
              <h3
                className={cn(
                  "flex items-baseline gap-2 bg-muted/50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                  divider && "border-b border-border",
                )}
              >
                {row.label}
                <span className="font-normal normal-case tabular-nums opacity-70">
                  {row.count}
                </span>
              </h3>
            ) : (
              <div className={cn(divider && "border-b border-border")}>
                <JobRow job={row.job} onDelete={onDelete} onRetry={onRetry} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
