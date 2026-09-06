import { Link } from "react-router-dom";
import { AudioLines, Clock, RotateCw, Trash2, Users } from "lucide-react";
import type { Job } from "@/lib/api";
import { de } from "@/i18n/de";
import { cn, formatDate, formatDuration } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { JobStatusBadge } from "@/components/jobs/JobStatusBadge";
import { isActive, isLegacy } from "@/components/jobs/jobFilters";

interface JobRowProps {
  job: Job;
  onDelete: (job: Job) => void;
  onRetry: (job: Job) => void;
}

/** Colour of the leading tile — the only status hint a finished row needs. */
function tileClass(job: Job): string {
  if (job.status === "failed" || job.status === "canceled") {
    return "bg-destructive/10 text-destructive";
  }
  if (isActive(job)) return "bg-primary/10 text-primary";
  return "bg-secondary text-muted-foreground";
}

export function JobRow({ job, onDelete, onRetry }: JobRowProps) {
  const running = isActive(job);
  const recoverable = job.status === "failed" || job.status === "canceled";

  return (
    <div className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-accent/50">
      <span
        aria-hidden
        className={cn(
          "mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg",
          tileClass(job),
        )}
      >
        <AudioLines className="size-4" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <Link
              to={`/job/${job.id}`}
              className="block truncate font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {job.title || de.jobs.untitled}
            </Link>

            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span className="tabular-nums">
                {formatDate(job.service_date ?? job.created_at)}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="size-3.5" />
                {formatDuration(job.duration_s)}
              </span>
              {job.speaker_count ? (
                <span className="inline-flex items-center gap-1.5">
                  <Users className="size-3.5" />
                  {job.speaker_count} {de.units.speakers}
                </span>
              ) : null}
              {isLegacy(job) && (
                <Badge variant="outline" className="px-2 py-0 text-[11px] font-normal">
                  {de.jobs.legacy}
                </Badge>
              )}
            </div>
          </div>

          {/* Plain buttons rather than a menu: the list clips its own
              overflow, so nothing here may pop out of the row. */}
          <div className="flex shrink-0 items-center gap-1">
            {job.status !== "done" && <JobStatusBadge status={job.status} />}
            {recoverable && (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => onRetry(job)}
                aria-label={de.jobs.retry}
                title={de.jobs.retry}
                className="text-muted-foreground hover:text-foreground"
              >
                <RotateCw />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => onDelete(job)}
              aria-label={de.jobs.delete}
              title={de.jobs.delete}
              className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 />
            </Button>
          </div>
        </div>

        {running && (
          <div className="mt-2.5 space-y-1.5">
            <Progress value={job.progress} indeterminate={job.status === "queued"} />
            <p className="text-xs text-muted-foreground">
              {job.message ?? de.status[job.status]}
            </p>
          </div>
        )}

        {job.status === "failed" && job.error && (
          <p className="mt-2.5 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {job.error}
          </p>
        )}
      </div>
    </div>
  );
}
