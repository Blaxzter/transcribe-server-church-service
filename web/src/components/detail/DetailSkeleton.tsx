import { de } from "@/i18n/de";
import { cn } from "@/lib/utils";
import { DETAIL_GRID, SIDEBAR_PANE, TRANSCRIPT_PANE } from "@/components/detail/panes";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";

/** Placeholder for the whole page while the job is being fetched. */
export function DetailSkeleton() {
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-3">
          <Skeleton className="h-7 flex-1 basis-64" />
          <Skeleton className="h-7 w-44" />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-5">
          <Skeleton className="h-22 w-full" />
          <Skeleton className="mt-3 h-8 w-56" />
        </CardContent>
      </Card>
      <div className={DETAIL_GRID}>
        {/* Same clip as the real page: the panes are fixed-height, so their
            placeholder rows have to be cut off at the card border. */}
        <Card className={cn("flex flex-col overflow-hidden", TRANSCRIPT_PANE)}>
          <TranscriptSkeleton />
        </Card>
        <Card className={cn("flex flex-col overflow-hidden", SIDEBAR_PANE)}>
          <SidebarSkeleton />
        </Card>
      </div>
    </div>
  );
}

/** Placeholder inside the sidebar pane: the tab bar plus one panel of text. */
export function SidebarSkeleton() {
  return (
    <CardContent className="space-y-4 pt-5" role="status" aria-busy="true">
      <span className="sr-only">{de.a11y.loading}</span>
      <Skeleton className="h-9 w-full" />
      <SkeletonText lines={6} />
    </CardContent>
  );
}

/** Placeholder rows inside the transcript pane, shaped like real segments. */
export function TranscriptSkeleton() {
  return (
    <div className="space-y-5 p-5" role="status" aria-busy="true">
      <span className="sr-only">{de.a11y.loading}</span>
      {Array.from({ length: 7 }, (_, index) => (
        <div key={index} className="flex gap-3">
          <Skeleton className="h-3.5 w-10 shrink-0" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className={index % 3 === 0 ? "h-3.5 w-2/3" : "h-3.5 w-5/6"} />
          </div>
        </div>
      ))}
    </div>
  );
}
