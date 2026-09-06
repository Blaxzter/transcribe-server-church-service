import { de } from "@/i18n/de";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Placeholder shaped like JobsToolbar plus JobList, so nothing jumps once the
 * data lands — the toolbar only appears with the jobs, and without a stand-in
 * the whole list would slide down by its height.
 */
export function JobListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div role="status" aria-label={de.a11y.loading} className="space-y-4">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton className="h-9 min-w-56 flex-1" />
          <Skeleton className="h-9 w-36" />
          <Skeleton className="h-9 w-36" />
        </div>
        <Skeleton className="h-4 w-56" />
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="border-b border-border bg-muted/50 px-4 py-2">
          <Skeleton className="h-3 w-24" />
        </div>
        {Array.from({ length: rows }, (_, index) => (
          <div
            key={index}
            className="flex items-start gap-3 border-b border-border px-4 py-3 last:border-b-0"
          >
            <Skeleton className="mt-0.5 size-9 shrink-0 rounded-lg" />
            <div className="min-w-0 flex-1 space-y-2 py-0.5">
              <Skeleton
                className="h-4"
                style={{ width: `${45 + ((index * 13) % 35)}%` }}
              />
              <Skeleton className="h-3 w-52" />
            </div>
            <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
          </div>
        ))}
      </div>
    </div>
  );
}
